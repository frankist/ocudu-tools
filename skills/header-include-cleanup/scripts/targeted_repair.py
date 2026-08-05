#!/usr/bin/env python3
"""Compile-verified, minimal #include repair for the `targeted` cleanup level.

The `explicit` level applies every IWYU "should add" suggestion, because
IWYU's raw output gives no way to tell "this include is needed now that we
removed its provider" apart from "this include is pure self-sufficiency
bloat, the symbol already resolves fine through an untouched include" -
both look identical in its output.

`targeted` gets that distinction the only way it can be had: by verifying.
Apply the removals/forward-declares exactly as `forward-declare` does, then
recompile the very same TU IWYU was run on. Whatever still resolves is left
alone; only the symbols the compiler actually reports as missing get an
addition, and the addition used is the one IWYU itself already published for
that symbol - never a header guessed from thin air.

Scope of the guarantee: this only proves the edited file self-consistent
against its OWN associated TU. A distant consumer that relied on the edited
header re-exporting a symbol transitively is invisible here and is still only
caught by the skill's mandatory full-project rebuild (SKILL.md Phase 3).

Entry point: repair(). Returns a report dict; the caller owns backup/restore.
"""
import os
import re
import subprocess

# IWYU output section headers.
_ADD_HEADER_RE = re.compile(r"^(.*) should add these lines:$")
_REMOVE_HEADER_RE = re.compile(r"^(.*) should remove these lines:$")
_TOTAL_HEADER_RE = re.compile(r"^The full include-list for (.*):$")
_SECTION_END_RE = re.compile(r"^---$")

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+([<"][^">]+[>"])')
_REMOVE_LINE_RE = re.compile(r"^-\s*(.*)$")
_FOR_COMMENT_RE = re.compile(r"//\s*for\s+(.*)$")
_TRAILING_COMMENT_RE = re.compile(r"\s*//.*$")
_FWD_DECL_SYMBOL_RE = re.compile(r"\b(?:class|struct|union)\s+([A-Za-z_][\w:]*)\s*[;{]")
_FWD_DECL_ENUM_RE = re.compile(r"\benum(?:\s+(?:class|struct))?\s+([A-Za-z_][\w:]*)\s*[:;]")
_NESTED_CLASS_FWD_DECL_RE = re.compile(r"\b(?:class|struct)\s+[A-Za-z_]\w*::[\w:]*\s*;")

# Any diagnostic line of the shape `<file>:<line>:<col>: error: <message>`; both
# clang and GCC emit this shape, and IWYU (a clang front-end) emits clang's.
_ERROR_LINE_RE = re.compile(r"^(?P<file>[^\s][^:]*):(?P<line>\d+):(?P<col>\d+):\s+(?:fatal\s+)?error:\s+(?P<msg>.*)$")

# Missing-symbol diagnostics, paired with whether a forward declaration could
# possibly satisfy them. `needs_definition` means the symbol is used in a way
# no forward-declare can ever fix (free function, value context, complete-type
# requirement, elided default template arguments) - only the real header will
# do. Phrasing differs between clang and GCC, so both spellings are listed.
_MISSING_SYMBOL_PATTERNS = [
    (re.compile(r"use of undeclared identifier '([^']+)'"), True),
    (re.compile(r"'([^']+)' was not declared in this scope"), True),
    (re.compile(r"no member named '([^']+)' in namespace"), True),
    (re.compile(r"'([^']+)' is not a member of"), True),
    (re.compile(r"implicit instantiation of undefined template '([^']+)'"), True),
    (re.compile(r"too few template arguments for \w+ template '([^']+)'"), True),
    (re.compile(r"invalid use of incomplete type '(?:class |struct |union |enum )?([^']+)'"), True),
    (re.compile(r"(?:variable|field|member access into|parameter) has incomplete type '([^']+)'"), True),
    (re.compile(r"incomplete type '([^']+)'"), True),
    (re.compile(r"'([^']+)' has incomplete type"), True),
    (re.compile(r"unknown type name '([^']+)'"), False),
    (re.compile(r"'([^']+)' does not name a type"), False),
    (re.compile(r"no type named '([^']+)'"), False),
    (re.compile(r"no template named '([^']+)'"), False),
]


def _strip_trailing_comment(line):
    return _TRAILING_COMMENT_RE.sub("", line).rstrip()


def parse_raw_sections(text):
    """Split raw IWYU output into {file: {"add": [], "remove": [], "full": []}}.

    Unlike process_header.parse_sections this also keeps the "full include-list"
    body, which maps symbols onto complete header paths even for includes IWYU
    wants left exactly as they are."""
    sections = {}
    current_file = None
    current_kind = None
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        for regex, kind in ((_ADD_HEADER_RE, "add"), (_REMOVE_HEADER_RE, "remove"), (_TOTAL_HEADER_RE, "full")):
            m = regex.match(line)
            if m:
                current_file, current_kind = m.group(1), kind
                sections.setdefault(current_file, {"add": [], "remove": [], "full": []})
                break
        else:
            if _SECTION_END_RE.match(line):
                current_file = current_kind = None
                continue
            if current_file and current_kind and line.strip():
                sections[current_file][current_kind].append(line)
    return sections


def symbols_of_line(line):
    """Symbols an IWYU add-line provides.

    For an #include line they come from IWYU's own trailing `// for a, b`
    annotation - this is the whole reason the RAW output is parsed rather than
    the filtered one. For a forward-declare line the symbol is the declared
    name itself."""
    if _INCLUDE_RE.match(line):
        m = _FOR_COMMENT_RE.search(line)
        if not m:
            return []
        names = []
        for part in m.group(1).split(","):
            # A long annotation gets truncated by --max_line_length, leaving a
            # trailing `foo (pt...`; keep the intact leading identifier only.
            name = part.strip().split(" ")[0].strip().rstrip(".")
            if name and not name.endswith("."):
                names.append(name)
        return names
    return [s.rsplit("::", 1)[-1]
            for s in _FWD_DECL_SYMBOL_RE.findall(line) + _FWD_DECL_ENUM_RE.findall(line)]


def build_symbol_tables(raw_text):
    """{file: {"add": {symbol: line}, "full": {symbol: include_line}}} from raw
    IWYU output - the deferred decision this level relies on: if symbol X later
    turns out to be missing, IWYU has already said which header provides it."""
    tables = {}
    for path, body in parse_raw_sections(raw_text).items():
        add_map, full_map = {}, {}
        for line in body["add"]:
            for sym in symbols_of_line(line):
                add_map.setdefault(sym, line)
        for line in body["full"]:
            if not _INCLUDE_RE.match(line):
                continue
            for sym in symbols_of_line(line):
                full_map.setdefault(sym, line)
        tables[path] = {"add": add_map, "full": full_map}
    return tables


def removed_includes_of(raw_text, path):
    """The `#include` statements IWYU wants dropped from `path`, comment-free."""
    body = parse_raw_sections(raw_text).get(path)
    if not body:
        return []
    out = []
    for line in body["remove"]:
        m = _REMOVE_LINE_RE.match(line.strip())
        stmt = _strip_trailing_comment(m.group(1) if m else line).strip()
        if _INCLUDE_RE.match(stmt):
            out.append(stmt)
    return out


def normalize_symbol(name):
    """`ocudu::detail::foo<int, 3>*` -> `foo`."""
    name = name.strip().strip("*&").strip()
    depth = 0
    cut = len(name)
    for i, ch in enumerate(name):
        if ch == "<":
            if depth == 0:
                cut = i
            depth += 1
        elif ch == ">":
            depth -= 1
    name = name[:cut]
    for prefix in ("class ", "struct ", "union ", "enum ", "const ", "typename "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name.rsplit("::", 1)[-1].strip()


def parse_compile_errors(stderr):
    """[{file, symbol, needs_definition}] for every error naming a missing symbol.

    Downstream noise (`template argument 1 is invalid`, `expected ';'`) names no
    identifier and is deliberately not matched - chasing it invents symbols that
    were never missing."""
    found = []
    seen = set()
    for line in stderr.split("\n"):
        m = _ERROR_LINE_RE.match(line.rstrip())
        if not m:
            continue
        msg = m.group("msg")
        for regex, needs_def in _MISSING_SYMBOL_PATTERNS:
            hit = regex.search(msg)
            if not hit:
                continue
            symbol = normalize_symbol(hit.group(1))
            if not symbol:
                break
            key = (os.path.abspath(m.group("file")), symbol)
            if key not in seen:
                seen.add(key)
                found.append({"file": key[0], "symbol": symbol, "needs_definition": needs_def,
                              "diagnostic": msg[:160]})
            break
    return found


def has_compile_error(returncode, stderr):
    """IWYU's exit code is not a reliable pass/fail on its own (it reports
    suggestions through it), so an explicit `error:` diagnostic is what counts."""
    return returncode != 0 or bool(_ERROR_LINE_RE.search(stderr) or re.search(r"^.*\berror:", stderr, re.M))


def include_search_dirs(cmd_list):
    dirs = []
    i = 0
    while i < len(cmd_list):
        arg = cmd_list[i]
        if arg in ("-I", "-isystem", "-iquote", "-idirafter"):
            if i + 1 < len(cmd_list):
                dirs.append(cmd_list[i + 1])
            i += 2
            continue
        if arg.startswith("-I") and len(arg) > 2:
            dirs.append(arg[2:])
        i += 1
    return dirs


def resolve_include_path(stmt, search_dirs, includer_dir, repo_root):
    m = _INCLUDE_RE.match(stmt)
    if not m:
        return None
    spec = m.group(1)
    rel = spec[1:-1]
    candidates = []
    if spec.startswith('"'):
        candidates.append(os.path.join(includer_dir, rel))
    for d in search_dirs:
        candidates.append(os.path.join(d if os.path.isabs(d) else os.path.join(repo_root, d), rel))
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def find_defining_removed_include(symbol, removed_stmts, search_dirs, includer_dir, repo_root, strip_fn):
    """Which of the includes THIS run removed actually declared `symbol`.

    Restoring one of our own removals is the only "add" allowed outside IWYU's
    published suggestions: it is a verified undo, not a guess."""
    best = None
    best_score = 0
    decl_re = re.compile(r"(?:\b(?:class|struct|enum|union|using|typedef)\s+" + re.escape(symbol) +
                         r"\b)|(?:\b" + re.escape(symbol) + r"\s*[(<])")
    word_re = re.compile(r"\b" + re.escape(symbol) + r"\b")
    for stmt in removed_stmts:
        path = resolve_include_path(stmt, search_dirs, includer_dir, repo_root)
        if not path:
            continue
        try:
            with open(path, errors="replace") as f:
                body = strip_fn(f.read())
        except OSError:
            continue
        score = 2 if decl_re.search(body) else (1 if word_re.search(body) else 0)
        if score > best_score:
            best, best_score = stmt, score
    return best


def _already_present(file_text, statement):
    target = re.sub(r"\s+", " ", statement).strip()
    for line in file_text.split("\n"):
        if re.sub(r"\s+", " ", _strip_trailing_comment(line)).strip() == target:
            return True
    return False


def _splice(lines, statement):
    """Place `statement` in the file's include block.

    Straight after the last #include when there is one. Otherwise (the whole
    include block was just removed) right below `#pragma once`/the include
    guard, re-establishing the single blank line either side that clang-format
    will not add back on its own."""
    last_include = None
    guard = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*#\s*include\b", line):
            last_include = i
        elif re.match(r"^\s*#\s*pragma\s+once\b", line) or (guard is None and re.match(r"^\s*#\s*define\b", line)):
            guard = i
    if last_include is not None:
        return lines[:last_include + 1] + [statement] + lines[last_include + 1:]
    if guard is None:
        for i, line in enumerate(lines):
            if line.strip() and not line.lstrip().startswith("//"):
                guard = i - 1
                break
        else:
            guard = len(lines) - 1
    tail = guard + 1
    while tail < len(lines) and not lines[tail].strip():
        tail += 1
    return lines[:guard + 1] + ["", statement, ""] + lines[tail:]


def apply_addition(path, statement):
    """Insert `statement` into `path`. False if it is already there."""
    with open(path) as f:
        text = f.read()
    if _already_present(text, statement):
        return False
    with open(path, "w") as f:
        f.write("\n".join(_splice(text.split("\n"), statement)))
    return True


def drop_superseded_forward_declares(path, original_text, provider_path, strip_fn):
    """Delete forward-declares THIS run added whose symbols the just-added
    header declares outright.

    A removal is applied together with the forward-declare meant to replace it.
    When the compile then proves the replacement insufficient and the real
    header goes (back) in, those declarations are pure leftovers of a
    substitution that did not hold - keeping them would leave a diff that
    changes nothing but noise. Only lines absent from the pre-run content are
    ever eligible, so nothing hand-written is touched."""
    try:
        with open(provider_path, errors="replace") as f:
            provider_body = strip_fn(f.read())
    except OSError:
        return []
    with open(path) as f:
        current = f.read()
    original_norm = {re.sub(r"\s+", " ", line).strip() for line in original_text.split("\n")}
    lines = current.split("\n")
    kept, dropped = [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        norm = re.sub(r"\s+", " ", _strip_trailing_comment(line)).strip()
        symbols = symbols_of_line(line) if norm and not _INCLUDE_RE.match(line) else []
        if symbols and norm not in original_norm and all(
                re.search(r"\b(?:class|struct|union|enum)\s+(?:\w+\s+)?" + re.escape(s) + r"\b", provider_body)
                for s in symbols):
            dropped.append(norm)
            i += 1
            # The insertion came with its own separating blank line; leaving that
            # behind would show up as a pure-whitespace hunk in the diff.
            if i < len(lines) and not lines[i].strip():
                i += 1
            elif kept and not kept[-1].strip():
                kept.pop()
            continue
        kept.append(line)
        i += 1
    if dropped:
        with open(path, "w") as f:
            f.write("\n".join(kept))
    return dropped


_CPP_SUFFIXES = (".cpp", ".cc")


def resolve_addition(missing, table, removed_stmts, file_text, search_dirs, repo_root, strip_fn):
    """The exact line to add for one missing symbol, or (None, reason).

    Order: IWYU's own suggestion for the symbol, then the complete header path
    IWYU listed for it, then an undo of one of this run's own removals. A
    forward-declare suggestion is upgraded to a real #include whenever the
    diagnostic proves a declaration cannot satisfy the usage - or the target
    is a .cpp, which never gets a bare forward-declare (see
    strip_iwyu_output.py's "Why a .cpp target never gets a bare
    forward-declare": a .cpp has no downstream consumer to amortize the
    forward-declare's cost over, so it buys nothing while adding the same
    fragility a header risks)."""
    symbol = missing["symbol"]
    includer_dir = os.path.dirname(missing["file"])
    is_cpp = missing["file"].endswith(_CPP_SUFFIXES)
    entry = table.get("add", {}).get(symbol)

    if entry is not None:
        statement = _strip_trailing_comment(entry).strip()
        if _INCLUDE_RE.match(statement):
            return statement, "iwyu_add_include"
        if not is_cpp and not missing["needs_definition"] and not _NESTED_CLASS_FWD_DECL_RE.search(statement):
            # Same safety filtering a forward-declare gets at `forward-declare`
            # level: defaults stripped so it can never collide with the real
            # declaration's defaults.
            from strip_iwyu_output import strip_template_defaults_in_line
            return strip_template_defaults_in_line(statement), "iwyu_add_forward_declare"

    full_entry = table.get("full", {}).get(symbol)
    if full_entry is not None:
        statement = _strip_trailing_comment(full_entry).strip()
        if _INCLUDE_RE.match(statement) and not _already_present(file_text, statement):
            return statement, "iwyu_full_include_list"

    restored = find_defining_removed_include(symbol, removed_stmts, search_dirs, includer_dir, repo_root, strip_fn)
    if restored is not None:
        return restored, "restored_own_removal"

    return None, f"no provider known for '{symbol}'"


_NS_WRAP_OPEN_RE = re.compile(r"^namespace\s+([A-Za-z_]\w*)\s*\{\s*$")
_NS_WRAP_CLOSE_RE = re.compile(r"^\}\s*(?://\s*namespace\s+([A-Za-z_]\w*))?\s*$")

_PROJECT_ENUM_DEF_RE = re.compile(r"\benum(?:\s+(?:class|struct))?\s+([A-Za-z_]\w*)\b[^;{]*\{")
_PROJECT_CLASS_DEF_RE = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)\b[^;{]*\{")
_PROJECT_ALIAS_RE = re.compile(r"\busing\s+([A-Za-z_]\w*)\s*=")
_PROJECT_TYPEDEF_RE = re.compile(r"\btypedef\b[^;{}]*?\b([A-Za-z_]\w*)\s*;")


def _build_project_header_index(include_root, strip_fn):
    """Map every type/enum/alias NAME defined (not merely forward-declared) in
    the project's own public headers to the header(s) that define it.

    Built once per upgrade_cpp_forward_declares() call and used only as a
    fallback when a symbol's home header was never touched by this run, so
    find_defining_removed_include() has nothing to check. Still guess-free:
    a lookup is only ever trusted when it names exactly one file (see
    find_declaring_project_header)."""
    index = {}
    if not os.path.isdir(include_root):
        return index
    for dirpath, _, filenames in os.walk(include_root):
        for fn in filenames:
            if not fn.endswith((".h", ".hpp")):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, errors="replace") as f:
                    body = strip_fn(f.read())
            except OSError:
                continue
            for regex in (_PROJECT_ENUM_DEF_RE, _PROJECT_CLASS_DEF_RE, _PROJECT_ALIAS_RE, _PROJECT_TYPEDEF_RE):
                for m in regex.finditer(body):
                    index.setdefault(m.group(1), set()).add(path)
    return index


def find_declaring_project_header(symbol, project_index, include_root):
    """The project header defining `symbol`, if exactly one such header exists.

    Broader than find_defining_removed_include() - not limited to this run's
    own edits - but bounded by the same never-guess rule: two or more
    candidates (name reused in different scopes) is treated as unknown, not
    resolved arbitrarily."""
    paths = project_index.get(symbol)
    if not paths or len(paths) != 1:
        return None
    rel = os.path.relpath(next(iter(paths)), include_root)
    return f'#include "{rel}"'


def _scan_fwd_decl_block(lines, i):
    """Scan the `namespace X { ... }` block opening at line i (nesting, e.g.
    `namespace ocudu { namespace ocucp { ... } }`, is expected and descended
    into). Returns (close_idx, symbols) if every line at every depth is
    either a nested namespace wrapper of the same shape or a plain
    forward-declare; symbols collects every declared name regardless of
    depth. Returns (None, []) if anything else appears (a real definition, an
    #include, unbalanced braces) - the caller leaves such a block untouched
    rather than edit around content it does not understand."""
    m_open = _NS_WRAP_OPEN_RE.match(lines[i].strip())
    ns = m_open.group(1)
    j = i + 1
    symbols = []
    while j < len(lines):
        stripped = lines[j].strip()
        m_close = _NS_WRAP_CLOSE_RE.match(stripped)
        if m_close and (m_close.group(1) is None or m_close.group(1) == ns):
            return (j, symbols) if symbols else (None, [])
        if not stripped:
            j += 1
            continue
        if _NS_WRAP_OPEN_RE.match(stripped):
            nested_close, nested_symbols = _scan_fwd_decl_block(lines, j)
            if nested_close is None:
                return None, []
            symbols.extend(nested_symbols)
            j = nested_close + 1
            continue
        if "{" in stripped or "}" in stripped:
            return None, []
        sym = None
        for regex in (_FWD_DECL_SYMBOL_RE, _FWD_DECL_ENUM_RE):
            m = regex.search(stripped)
            if m:
                sym = m.group(1).rsplit("::", 1)[-1]
                break
        if sym is None:
            return None, []
        symbols.append(sym)
        j += 1
    return None, []


def upgrade_cpp_forward_declares(cmd_list, repo_root, files_to_modify, raw_iwyu_text, strip_fn):
    """Swap any bare forward-declare block left in a .cpp target for the real
    header this run removed and that declares the same symbol.

    strip_iwyu_output.py already tries to avoid ever emitting a bare
    forward-declare for a .cpp - a .cpp has no downstream consumer to
    amortize the cost over, so forward-declaring there buys nothing (see its
    docstring). That upgrade only works when IWYU's own "full include-list"
    names a real #include for the symbol. When IWYU's own analysis considers
    a forward-declare fully sufficient, its "full include-list" shows the
    forward-declare there too, not a #include - so there is nothing to
    upgrade to at that point, and one slips through - and the symbol need not
    even be one this run touched at all (e.g. it was already only ever
    forward-declared, transitively, before this run existed). This pass
    catches those afterwards. It first tries the header THIS RUN itself
    removed, if it declares the symbol (the same lookup
    find_defining_removed_include does for the validation-repair loop above);
    failing that, it falls back to a project-wide search of the repo's own
    public headers (find_declaring_project_header), trusting a match only
    when it is the single unambiguous definition.

    Only acts on a `namespace X { <only simple forward-declares> } // namespace
    X` block, and only when EVERY symbol inside resolves; otherwise the block
    is left untouched rather than risk a partial, guessed edit. Returns the
    list of files actually changed."""
    search_dirs = include_search_dirs(cmd_list)
    include_root = os.path.join(repo_root, "include")
    project_index = None
    touched = []
    for path in files_to_modify:
        if not path or not path.endswith((".cpp", ".cc")):
            continue
        removed_stmts = removed_includes_of(raw_iwyu_text, path)
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            continue
        lines = text.split("\n")
        # A parallel, comment/string-blanked view used only to find a rejected
        # block's true extent by counting literal braces - never to decide
        # content, so a stray brace inside a comment can't cause a wrong count.
        clean_lines = strip_fn(text).split("\n")
        out = []
        changed = False
        i = 0
        includer_dir = os.path.dirname(path)
        while i < len(lines):
            m_open = _NS_WRAP_OPEN_RE.match(lines[i].strip())
            if not m_open:
                out.append(lines[i])
                i += 1
                continue
            close_idx, symbols = _scan_fwd_decl_block(lines, i)
            if close_idx is None:
                # Anything this scan doesn't understand (a real definition, an
                # #include, unbalanced braces) - copy the whole span through
                # untouched. Critically this must be the WHOLE span: letting the
                # outer loop re-enter a nested `namespace X { ... }` on its own
                # next iteration would edit it in isolation while still inside
                # this block's still-open outer braces, splicing a real #include
                # into the middle of a namespace scope. The opening line itself
                # contributes one unmatched '{', so depth starts at 1.
                depth = clean_lines[i].count("{") - clean_lines[i].count("}")
                end = i
                for k in range(i + 1, len(lines)):
                    depth += clean_lines[k].count("{") - clean_lines[k].count("}")
                    if depth <= 0:
                        end = k
                        break
                else:
                    end = None
                if end is None:
                    out.append(lines[i])
                    i += 1
                    continue
                out.extend(lines[i:end + 1])
                i = end + 1
                continue
            replacements = []
            all_resolved = True
            for sym in symbols:
                stmt = find_defining_removed_include(sym, removed_stmts, search_dirs, includer_dir, repo_root,
                                                     strip_fn)
                if stmt is None:
                    if project_index is None:
                        project_index = _build_project_header_index(include_root, strip_fn)
                    stmt = find_declaring_project_header(sym, project_index, include_root)
                if stmt is None:
                    all_resolved = False
                    break
                if stmt not in replacements:
                    replacements.append(stmt)
            if not all_resolved:
                out.append(lines[i])
                i += 1
                continue
            # The replacements are plain #include lines, so they blend into the
            # include block above like any other addition - drop the blank
            # line that used to separate it from the wrapped namespace block.
            # Whatever blank line separated the block from what follows
            # (typically the first line of real code) is left in place.
            if out and not out[-1].strip():
                out.pop()
            out.extend(replacements)
            changed = True
            i = close_idx + 1
        if changed:
            with open(path, "w") as f:
                f.write("\n".join(out))
            touched.append(path)
    return touched


def repair(cmd_list, repo_root, files_to_modify, raw_iwyu_text, strip_fn, pre_run_contents=None,
           rounds=3, timeout=120, formatter=None):
    """Validate the already-applied edits and patch up only what actually broke.

    Returns {"ok", "rounds", "additions": {file: [statements]}, "reason",
    "stderr_tail"}. On ok=False the caller must restore its backups - this
    function never leaves a file half-migrated by design, but it also never
    reverts on its own, since only the caller knows the pre-run content."""
    targets = [f for f in files_to_modify if f]
    tables = build_symbol_tables(raw_iwyu_text)
    # Pooled across every file in the run, not just the one a missing symbol
    # surfaced in: a header removed from the .h can just as easily be the
    # provider of a symbol that only breaks in the associated .cpp, since
    # that's exactly what removing a transitively-relied-on include does.
    all_removed = []
    for f in targets:
        for stmt in removed_includes_of(raw_iwyu_text, f):
            if stmt not in all_removed:
                all_removed.append(stmt)
    search_dirs = include_search_dirs(cmd_list)
    pre_run_contents = pre_run_contents or {}
    additions = {}
    report = {"ok": False, "rounds": 0, "additions": additions, "dropped_forward_declares": {},
              "reason": None, "stderr_tail": ""}

    for attempt in range(1, rounds + 1):
        report["rounds"] = attempt
        try:
            proc = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout, cwd=repo_root)
        except subprocess.TimeoutExpired:
            report["reason"] = f"validation compile timed out after {timeout}s"
            return report
        if not has_compile_error(proc.returncode, proc.stderr):
            report["ok"] = True
            return report

        report["stderr_tail"] = proc.stderr[-1500:]
        missing = parse_compile_errors(proc.stderr)
        relevant = [m for m in missing if m["file"] in targets]
        if not missing:
            report["reason"] = "validation failed with no identifiable missing symbol"
            return report
        if not relevant:
            # Breakage in a file this run never touched is the transitive
            # re-export failure mode - out of reach of a local repair.
            report["reason"] = ("validation failed outside the edited files: " +
                                ", ".join(sorted({f"{os.path.basename(m['file'])}:{m['symbol']}" for m in missing})))
            return report

        progress = False
        for m in relevant:
            with open(m["file"]) as f:
                file_text = f.read()
            statement, source = resolve_addition(m, tables.get(m["file"], {}), all_removed,
                                                 file_text, search_dirs, repo_root, strip_fn)
            if statement is None:
                report["reason"] = source
                return report
            if apply_addition(m["file"], statement):
                additions.setdefault(m["file"], []).append(f"{statement}  [{source}]")
                progress = True
                provider = resolve_include_path(statement, search_dirs, os.path.dirname(m["file"]), repo_root)
                if provider and m["file"] in pre_run_contents:
                    dropped = drop_superseded_forward_declares(m["file"], pre_run_contents[m["file"]],
                                                               provider, strip_fn)
                    if dropped:
                        report["dropped_forward_declares"].setdefault(m["file"], []).extend(dropped)
        if not progress:
            report["reason"] = ("no new fix could be applied for: " +
                                ", ".join(sorted({m["symbol"] for m in relevant})))
            return report
        if formatter:
            formatter(sorted(additions))

    report["reason"] = f"still not compiling after {rounds} repair rounds"
    return report
