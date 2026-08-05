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

Scope of the guarantee: proving the edited file self-consistent against its
OWN associated TU is not quite the same thing as proving the HEADER
self-sufficient - the associated TU can still transitively reach a symbol
through some OTHER include the header itself no longer provides, silently
masking a real gap in the header's own content (real incidents:
`pcch_configuration.h` and `prach_format_type.h`, both of which recompiled
their associated .cpp clean after losing their real provider of
`std::optional`/`uint8_t`, only to fail every OTHER consumer once the full
project rebuild forced the header to stand on its own). `repair()` therefore
also solo-compiles the header itself - see solo_compile_header() - as a
cheap, additional, unmaskable check. Neither check, alone or together, can
see a DISTANT consumer that relied on the edited header re-exporting a
symbol transitively; that class is still only caught by the skill's
mandatory full-project rebuild (SKILL.md Phase 3).

Entry point: repair(). Returns a report dict; the caller owns backup/restore.
"""
import os
import re
import subprocess
import tempfile

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
    # `enum` gets its own alternative (rather than folding into the plain
    # class/struct/union/using/typedef one) because its keyword can carry an
    # optional `class`/`struct` in between (`enum class X`) - a real incident:
    # this used to only match bare `enum X`, so `nr_band.h`'s own `enum class
    # nr_band { ... }` scored the same weak "bare word" match as
    # `band_helper.h` merely USING `nr_band` everywhere without defining it,
    # and the heavier header won the tie by appearing first.
    decl_re = re.compile(r"(?:\b(?:class|struct|union|using|typedef)\s+" + re.escape(symbol) + r"\b)"
                         r"|(?:\benum(?:\s+(?:class|struct))?\s+" + re.escape(symbol) + r"\b)"
                         r"|(?:\b" + re.escape(symbol) + r"\s*[(<])")
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
    from strip_iwyu_output import canonicalize_c_header_include

    symbol = missing["symbol"]
    includer_dir = os.path.dirname(missing["file"])
    is_cpp = missing["file"].endswith(_CPP_SUFFIXES)
    entry = table.get("add", {}).get(symbol)

    if entry is not None:
        statement = _strip_trailing_comment(entry).strip()
        if _INCLUDE_RE.match(statement):
            return canonicalize_c_header_include(statement), "iwyu_add_include"
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
            # IWYU's full include-list just names A header in the TU's graph
            # that touches this symbol - not necessarily its defining one (it
            # can equally be a heavy header that merely USES the symbol
            # pervasively while itself #including the real definition). Verify
            # before trusting it; an unresolvable path (system header, symbol
            # defined outside include/) can't be checked and is trusted as
            # before.
            candidate_path = resolve_include_path(statement, search_dirs, includer_dir, repo_root)
            if candidate_path is None or _is_definition_of(symbol, candidate_path, strip_fn):
                return canonicalize_c_header_include(statement), "iwyu_full_include_list"

    restored = find_defining_removed_include(symbol, removed_stmts, search_dirs, includer_dir, repo_root, strip_fn)
    if restored is not None:
        return canonicalize_c_header_include(restored), "restored_own_removal"

    return None, f"no provider known for '{symbol}'"


_NS_WRAP_OPEN_RE = re.compile(r"^namespace\s+([A-Za-z_]\w*)\s*\{\s*$")
_NS_WRAP_CLOSE_RE = re.compile(r"^\}\s*(?://\s*namespace\s+([A-Za-z_]\w*))?\s*$")

_PROJECT_ENUM_DEF_RE = re.compile(r"\benum(?:\s+(?:class|struct))?\s+([A-Za-z_]\w*)\b[^;{]*\{")
_PROJECT_CLASS_DEF_RE = re.compile(r"\b(?:class|struct)\s+([A-Za-z_]\w*)\b[^;{]*\{")
_PROJECT_ALIAS_RE = re.compile(r"\busing\s+([A-Za-z_]\w*)\s*=")
_PROJECT_TYPEDEF_RE = re.compile(r"\btypedef\b[^;{}]*?\b([A-Za-z_]\w*)\s*;")


def _blank_template_param_lists(text):
    """Blank the CONTENTS of every top-level `template <...>` parameter list
    (spaces, preserving newlines) before the definition regexes below run.

    Without this, `template <class R, class... Args> class unique_function
    {` misattributes the definition to `R` - `_PROJECT_CLASS_DEF_RE` just
    looks for the next "class NAME" before a "{", and "class R" inside the
    parameter list matches first. A template parameter declared with the
    `class`/`struct`/`typename` keyword is not a definition of anything."""
    out = list(text)
    n = len(text)
    i = 0
    while i < n:
        if text[i:i + 8] == "template" and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
            j = i + 8
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] == "<":
                depth = 1
                k = j + 1
                while k < n and depth > 0:
                    if text[k] == "<":
                        depth += 1
                    elif text[k] == ">":
                        depth -= 1
                    k += 1
                for p in range(j, k):
                    if out[p] != "\n":
                        out[p] = " "
                i = k
                continue
        i += 1
    return "".join(out)


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
                    body = _blank_template_param_lists(strip_fn(f.read()))
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


def _is_definition_of(symbol, header_path, strip_fn):
    """Whether header_path's own on-disk content actually DEFINES symbol (an
    enum/class/struct/alias/typedef), not merely uses it or reaches it by
    itself #including its real header.

    Used to reject a resolution candidate that only reaches a symbol by
    using it pervasively rather than defining it - real incident:
    `search_space.h` needed `nr_band`, and IWYU's own "full include-list"
    named `band_helper.h` (which uses `nr_band` throughout its own body,
    and also #includes nr_band.h, but does not define it) ahead of the
    much lighter `nr_band.h` (the actual definition) ever being considered.
    Only ever narrows a candidate down, never invents one - an unresolvable
    path (a system header, a symbol defined outside include/) simply
    returns False and the caller falls through to its next resolution
    step."""
    try:
        with open(header_path, errors="replace") as f:
            body = _blank_template_param_lists(strip_fn(f.read()))
    except OSError:
        return False
    for regex in (_PROJECT_ENUM_DEF_RE, _PROJECT_CLASS_DEF_RE, _PROJECT_ALIAS_RE, _PROJECT_TYPEDEF_RE):
        for m in regex.finditer(body):
            if m.group(1) == symbol:
                return True
    return False


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
    from strip_iwyu_output import canonicalize_c_header_include

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
                stmt = canonicalize_c_header_include(stmt)
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


_ENUM_FWD_DECL_CORE_RE = re.compile(r"^enum(?:\s+(?:class|struct))?\s+([A-Za-z_][\w:]*)\s*(?::[^;{}]*)?;$")
_TEMPLATE_CLASS_FWD_DECL_CORE_RE = re.compile(r"^(?:class|struct)\s+([A-Za-z_][\w:]*)\s*;$")
_NS_PREFIX_ONE_RE = re.compile(r"^namespace\s+[A-Za-z_][\w:]*\s*\{\s*")
_TEMPLATE_KEYWORD_RE = re.compile(r"^template\s*<")


def _extract_fragile_fwd_decl_symbol(stripped_line):
    """If `stripped_line` is (optionally same-line-namespace-wrapped) nothing
    but a single enum OR template class/struct forward-declare, return its
    bare symbol name; else None.

    These are the two forward-declare shapes never left behind, in any file -
    see "Why enums never get forward-declared" in SKILL.md; a template
    forward-declare is fragile for the same reason plus one more: it must
    repeat every template parameter (post default-stripping) exactly, so a
    signature change upstream silently breaks it. Covers both IWYU's own
    one-line form (`namespace ocudu { enum class rnti_t : uint16_t; }`) and a
    bare body line inside a separately-opened multi-line namespace block (see
    _scan_fwd_decl_block), which has zero wraps on its own line.

    Requires `template <...>` (a parameter LIST) directly before the
    class/struct keyword, so an explicit template instantiation - which has
    no parameter list, just `template class Foo<Bar>;` or
    `extern template class Foo<Bar>;` with actual template ARGUMENTS after
    the class name - never matches and is always left untouched, wherever it
    already exists in a file."""
    s = stripped_line
    depth = 0
    while True:
        m = _NS_PREFIX_ONE_RE.match(s)
        if not m:
            break
        s = s[m.end():]
        depth += 1
    if depth:
        core = s.rstrip()
        trailing = 0
        while trailing < depth and core.endswith("}"):
            core = core[:-1].rstrip()
            trailing += 1
        if trailing != depth:
            return None
        s = core
    else:
        s = s.strip()
    m_enum = _ENUM_FWD_DECL_CORE_RE.match(s)
    if m_enum:
        return m_enum.group(1)
    m_tmpl = _TEMPLATE_KEYWORD_RE.match(s)
    if m_tmpl:
        i = m_tmpl.end()
        tdepth = 1
        while i < len(s) and tdepth > 0:
            if s[i] == "<":
                tdepth += 1
            elif s[i] == ">":
                tdepth -= 1
            i += 1
        if tdepth == 0:
            m_cls = _TEMPLATE_CLASS_FWD_DECL_CORE_RE.match(s[i:].strip())
            if m_cls:
                return m_cls.group(1)
    return None


_MAX_FRAGILE_FWD_DECL_SPAN = 6


def _match_fragile_fwd_decl_span(lines, start):
    """Like _extract_fragile_fwd_decl_symbol, but tolerates a template
    forward-declare's parameter list being split across multiple lines - seen
    in practice when fix_include merges a long one into an already-open
    namespace scope rather than wrapping it standalone. Returns
    (end_index, symbol) if lines[start:end_index+1] joined is a fragile
    forward-declare, else (start, None) - the single-line case is just the
    span start == end == the one line that already matched on its own."""
    symbol = _extract_fragile_fwd_decl_symbol(lines[start].strip())
    if symbol is not None:
        return start, symbol
    # Only worth accumulating if this line - once same-line namespace wraps
    # are peeled - opens a template parameter list without yet closing the
    # whole statement; anything else is definitely not a split candidate.
    s = lines[start].strip()
    while True:
        m = _NS_PREFIX_ONE_RE.match(s)
        if not m:
            break
        s = s[m.end():]
    if not _TEMPLATE_KEYWORD_RE.match(s) or ";" in s:
        return start, None
    joined = lines[start].strip()
    for end in range(start + 1, min(start + _MAX_FRAGILE_FWD_DECL_SPAN, len(lines))):
        joined = joined + " " + lines[end].strip()
        symbol = _extract_fragile_fwd_decl_symbol(joined)
        if symbol is not None:
            return end, symbol
        if ";" in lines[end]:
            break  # statement ended without ever matching - give up
    return start, None


def _drop_empty_namespace_wraps_once(lines):
    out = []
    i = 0
    while i < len(lines):
        m_open = _NS_WRAP_OPEN_RE.match(lines[i].strip())
        if m_open:
            ns = m_open.group(1)
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                m_close = _NS_WRAP_CLOSE_RE.match(lines[j].strip())
                if m_close and (m_close.group(1) is None or m_close.group(1) == ns):
                    i = j + 1
                    continue
        out.append(lines[i])
        i += 1
    return out


def _drop_empty_namespace_wraps(lines):
    """Repeat _drop_empty_namespace_wraps_once until stable, so an outer
    namespace block left empty by removing its only (now-resolved) inner
    block also gets cleaned up, not just the innermost one."""
    for _ in range(5):
        new_lines = _drop_empty_namespace_wraps_once(lines)
        if new_lines == lines:
            return new_lines
        lines = new_lines
    return lines


def remove_fragile_forward_declares(cmd_list, repo_root, files_to_modify, raw_iwyu_text, strip_fn):
    """Replace every enum or template class/struct forward-declare THIS RUN
    added with the real header, in any file - .h or .cpp - never leave one
    behind.

    An enum forward-declare must exactly repeat the real declaration's
    underlying type, and is outright illegal for a plain `enum` with no
    explicit underlying type. A template forward-declare must exactly repeat
    every template parameter (post default-stripping, see
    strip_template_defaults_in_line) - a signature change upstream silently
    breaks it. Both are fragile for a payoff too small to make worthwhile
    (unlike a plain, non-template class/struct, which can hide a genuinely
    heavy header behind the forward-declare and is left alone here).

    Resolution order mirrors upgrade_cpp_forward_declares: IWYU's own full
    include-list for the symbol, then a header THIS RUN itself removed and
    that really declares it (read from disk, not guessed), then a
    project-wide search of the repo's own public headers. Only touches
    symbols this run's own strip step added (checked against the raw IWYU
    "add" table for the file) - a forward-declare the file already had before
    this run is left alone.

    Falls back to leaving the forward-declare in place only if no real header
    can be found by any of the three routes above - rare, and still safe (a
    forward-declare that compiles beats none), just not the ideal outcome.
    Returns the list of files actually changed."""
    from strip_iwyu_output import canonicalize_c_header_include

    search_dirs = include_search_dirs(cmd_list)
    include_root = os.path.join(repo_root, "include")
    project_index = None
    tables = build_symbol_tables(raw_iwyu_text)
    all_removed = []
    for f in files_to_modify:
        if not f:
            continue
        for stmt in removed_includes_of(raw_iwyu_text, f):
            if stmt not in all_removed:
                all_removed.append(stmt)

    touched = []
    for path in files_to_modify:
        if not path:
            continue
        add_table = tables.get(path, {}).get("add", {})
        full_table = tables.get(path, {}).get("full", {})
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            continue
        lines = text.split("\n")
        includer_dir = os.path.dirname(path)
        out = []
        new_includes = []
        changed = False
        i = 0
        n = len(lines)
        while i < n:
            span_end, symbol = _match_fragile_fwd_decl_span(lines, i)
            if symbol is None:
                out.append(lines[i])
                i += 1
                continue
            symbol = symbol.rsplit("::", 1)[-1]
            if symbol not in add_table:
                out.extend(lines[i:span_end + 1])  # pre-existing, not something this run added
                i = span_end + 1
                continue
            stmt = None
            full_entry = full_table.get(symbol)
            if full_entry is not None:
                candidate = _strip_trailing_comment(full_entry).strip()
                if _INCLUDE_RE.match(candidate):
                    # Verify before trusting: IWYU's full include-list just names A
                    # header in the TU's graph that touches this symbol, which can be
                    # a heavy header that merely USES it pervasively rather than the
                    # one that actually defines it (real incident: `nr_band` resolved
                    # to `band_helper.h` instead of the far lighter `nr_band.h`).
                    candidate_path = resolve_include_path(candidate, search_dirs, includer_dir, repo_root)
                    if candidate_path is None or _is_definition_of(symbol, candidate_path, strip_fn):
                        stmt = candidate
            if stmt is None:
                stmt = find_defining_removed_include(symbol, all_removed, search_dirs, includer_dir, repo_root,
                                                     strip_fn)
            if stmt is None:
                if project_index is None:
                    project_index = _build_project_header_index(include_root, strip_fn)
                stmt = find_declaring_project_header(symbol, project_index, include_root)
            if stmt is None:
                out.extend(lines[i:span_end + 1])  # no real header known - keep the forward-declare
                i = span_end + 1
                continue
            stmt = canonicalize_c_header_include(stmt)
            if stmt not in new_includes:
                new_includes.append(stmt)
            changed = True  # span dropped - it collapses into new_includes below
            i = span_end + 1
        if not changed:
            continue
        out = _drop_empty_namespace_wraps(out)
        for stmt in new_includes:
            if not _already_present("\n".join(out), stmt):
                out = _splice(out, stmt)
        with open(path, "w") as f:
            f.write("\n".join(out))
        touched.append(path)
    return touched


_SRC_EXT_RE = re.compile(r"\.(?:cpp|cc|cxx)$", re.IGNORECASE)


def _find_source_arg(cmd_list):
    """The index of the original .cpp/.cc/.cxx source path inside an
    already-IWYU-sanitized command list - the one positional argument
    sanitize_command() passes through untouched. Swapping just this one
    argument for a synthetic TU keeps every -I/-D/-std flag identical to
    the real associated-TU check."""
    for i, p in enumerate(cmd_list):
        if not p.startswith("-") and _SRC_EXT_RE.search(p):
            return i
    return None


def _header_include_spec(header_path, search_dirs, repo_root):
    """The `#include "..."` spec a real consumer would use to reach
    header_path, resolved against the same -I/-iquote dirs the associated
    TU's own build uses - the shortest one, since a header can legally sit
    under more than one search dir. None if it isn't reachable from any of
    them (would mean the header can't be #included at all as things stand -
    never guessed, just skipped)."""
    best = None
    for d in search_dirs:
        base = os.path.normpath(d if os.path.isabs(d) else os.path.join(repo_root, d))
        try:
            rel = os.path.relpath(header_path, base)
        except ValueError:
            continue
        if rel.startswith(".."):
            continue
        if best is None or len(rel) < len(best):
            best = rel
    return best.replace(os.sep, "/") if best else None


def solo_compile_header(cmd_list, repo_root, header_path, timeout=30):
    """Whether header_path compiles standing entirely on its own - nothing
    assumed except its own #include list - and the raw IWYU stderr if not.

    Built by swapping the associated TU's own source-file argument for a
    synthetic one-liner that does nothing but `#include` the header, then
    running the exact same (already IWYU-sanitized) cmd_list against it -
    same -I/-D/-std flags, same IWYU binary, so every existing error-parsing
    helper (has_compile_error, parse_compile_errors) applies unchanged; a
    diagnostic naming a symbol used inside the header itself reports the
    header's own real path, which already satisfies repair()'s `m["file"]
    in targets` check with no remapping needed.

    This exists because the associated-TU check alone can be masked: that TU
    can still reach a symbol through some OTHER include the header itself no
    longer provides, so the header can silently stop being self-sufficient
    even while its own paired .cpp keeps compiling clean (real incidents:
    `pcch_configuration.h` losing `std::optional`, `prach_format_type.h`
    losing `uint8_t`/`strcmp`/`std::underlying_type_t` - both passed their
    associated-TU check and only broke once something ELSE in the full
    project rebuild needed the header standing alone). Compiling a
    single-#include TU can't be fooled that way: there is nothing else in it
    to mask a gap with.

    Returns (True, "") when the header can't be checked this way at all (no
    resolvable #include spec, no source-file argument to swap, or the check
    itself times out) - inconclusive is not the same as broken, and this
    must never be able to fail a header the rest of the pipeline handled
    fine."""
    search_dirs = include_search_dirs(cmd_list)
    spec = _header_include_spec(header_path, search_dirs, repo_root)
    if spec is None:
        return True, ""
    src_idx = _find_source_arg(cmd_list)
    if src_idx is None:
        return True, ""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False) as tmp:
            tmp.write(f'#include "{spec}"\n')
            tmp_path = tmp.name
        solo_cmd = list(cmd_list)
        solo_cmd[src_idx] = tmp_path
        try:
            proc = subprocess.run(solo_cmd, capture_output=True, text=True, timeout=timeout, cwd=repo_root)
        except subprocess.TimeoutExpired:
            return True, ""
        return not has_compile_error(proc.returncode, proc.stderr), proc.stderr
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


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
              "reason": None, "stderr_tail": "", "solo_header_findings": []}

    header_path = targets[0]
    # A header standing entirely on its own is strictly cheaper to check than
    # recompiling the whole associated TU (see solo_compile_header) and, once
    # true, never becomes false again across rounds (repair() only adds
    # things) - so it's only worth spending a round on until it first passes.
    solo_passed = False
    solo_timeout = min(timeout, 30)

    for attempt in range(1, rounds + 1):
        report["rounds"] = attempt
        solo_ok, solo_stderr = (True, "") if solo_passed else solo_compile_header(
            cmd_list, repo_root, header_path, timeout=solo_timeout)
        solo_passed = solo_passed or solo_ok

        try:
            proc = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout, cwd=repo_root)
        except subprocess.TimeoutExpired:
            report["reason"] = f"validation compile timed out after {timeout}s"
            return report
        assoc_ok = not has_compile_error(proc.returncode, proc.stderr)

        if solo_ok and assoc_ok:
            report["ok"] = True
            return report

        report["stderr_tail"] = (proc.stderr if not assoc_ok else solo_stderr)[-1500:]
        missing = []
        if not solo_ok:
            solo_missing = parse_compile_errors(solo_stderr)
            if attempt == 1:
                report["solo_header_findings"] = [f"{m['symbol']}: {m['diagnostic']}" for m in solo_missing]
            missing.extend(solo_missing)
        if not assoc_ok:
            missing.extend(parse_compile_errors(proc.stderr))
        seen_keys = set()
        deduped = []
        for m in missing:
            key = (m["file"], m["symbol"])
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(m)
        missing = deduped

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
