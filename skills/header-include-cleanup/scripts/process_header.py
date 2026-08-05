#!/usr/bin/env python3
"""Remove/forward-declare/targeted/explicit IWYU cleanup for a single project header.

Usage:
  process_header.py <header_abs_path> --repo <repo_root> --build-dir <build_dir>
                     [--level remove|forward-declare|targeted|explicit] [--dry-run]
                     [--default-fallback-tu <cpp_abs_path>]

Strategy:
  1. Find the header's own associated .cpp (same basename) in
     compile_commands.json. If found, run IWYU on that .cpp - IWYU's
     default behavior already reports for "associated" headers, no
     --check_also needed, and this avoids forcing instantiation of
     forward-declared/PIMPL members before their completing TU (a header
     checked from an unrelated TU can hit "incomplete type" errors on a
     perfectly legal PIMPL pattern). In this mode fix_include is allowed
     to touch both the header and its own .cpp - that pairing is correct
     and intentional (IWYU commonly needs to add/remove things in the
     .cpp too, e.g. a #include the .cpp only needed via the header).
  2. If no associated .cpp exists, resolve a fallback TU via
     find_fallback_tu.py and run IWYU on THAT, with
     -Xiwyu --check_also=<this one header only> - single header at a
     time, so a failure only costs this one header, never a whole batch.
     IMPORTANT: the fallback TU is only a *vehicle* to get IWYU to report
     on the target header - it is NOT meant to be edited itself, even
     though IWYU will also report on it (and its own associated header)
     as the "main file" of the compile. fix_include is explicitly
     restricted to the target header path only in this mode, so any
     unrelated changes IWYU found for the fallback TU/its header are
     computed but never applied.
  3. Parse the raw IWYU output through strip_iwyu_output.py at the
     requested --level, additionally dropping any dead/misattributed
     forward-declare additions (checked against the header's own current
     content), then feed the result to fix_include --nosafe_headers (so
     header files are eligible for removal too - fix_include's default,
     --safe_headers, silently refuses to remove anything from a .h).
  4. At --level targeted only: recompile the same TU and repair just the
     symbols that actually broke, using IWYU's own published provider for
     each (targeted_repair.py). Give up and restore the pre-run content
     rather than leave a file half-migrated.
  5. clang-format the touched files afterward, if a formatter is
     configured (see --clang-format-bin).
  6. With --measure-closure: preprocess the same TU before and after the
     edits and report the change in line count, i.e. how much C++ the
     parser no longer has to see. This is the only honest measure of
     whether a level bought anything - see preprocess_command().

Prints one JSON line to stdout describing the outcome:
  {"header": ..., "status": "removed"|"added"|"no_change"|"skipped", "detail": ..., "removed_lines": [...], "added_lines": [...]}
plus, with --measure-closure, {"closure": {"tu": ..., "before": N, "after": N, "saved": N}}.

IMPORTANT - this script only ever proves a change locally plausible, not
project-wide safe. A removal (or forward-declare addition) that looks
fine from a single TU's viewpoint can still break some OTHER file miles
away that relied on this header re-exporting a symbol transitively - or
break THIS SAME file if it uses the symbol in a way a forward-declare
can't satisfy (elided default template arguments, extern template
instantiation, by-value storage, a type alias which can never be
forward-declared at all). None of that is detectable from this script's
output alone. The skill's mandatory full-project-rebuild step after each
batch is what actually catches these - see SKILL.md phase 3.
"""
import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import targeted_repair  # noqa: E402  (needs SCRIPT_DIR on the path first)

STRIP_SCRIPT = os.path.join(SCRIPT_DIR, "strip_iwyu_output.py")
FIND_FALLBACK_SCRIPT = os.path.join(SCRIPT_DIR, "find_fallback_tu.py")

_BAD_GCC_FLAGS_PREFIXES = (
    "-Wno-maybe-uninitialized",
    "-Wno-error=stringop-overflow",
    "-Wno-error=array-bounds",
)

_ADD_HEADER_RE = re.compile(r"^(.*) should add these lines:$")
_REMOVE_HEADER_RE = re.compile(r"^(.*) should remove these lines:$")
_TOTAL_HEADER_RE = re.compile(r"^The full include-list for (.*):$")
_SECTION_END_RE = re.compile(r"^---$")
_FWD_DECL_SYMBOL_RE = re.compile(r"\b(?:class|struct)\s+([A-Za-z_][\w:]*)\s*;")
# The underlying-type clause is optional: `enum class Foo;` is a legal (and common)
# IWYU suggestion, and must be subject to the same dead-declare check as
# `enum class Foo : uint8_t;`.
_FWD_DECL_ENUM_RE = re.compile(r"\benum(?:\s+class)?\s+([A-Za-z_]\w*)\s*[:;]")


def load_compile_commands(build_dir):
    with open(os.path.join(build_dir, "compile_commands.json")) as f:
        return json.load(f)


def tu_for_command(entries, cmd, default_dir):
    """The TU a recorded compile command belongs to, and the directory it was
    recorded against.

    Matched on the command rather than taken from the caller because in unity
    mode the file compiled is the generated unity chunk, not the .cpp the edits
    target - a measurement labelled with the latter would misreport what was
    actually preprocessed. Relative -I paths resolve against the recorded
    directory, so it is preferred over the repo root."""
    for e in entries:
        if e["command"] == cmd:
            d = e.get("directory")
            return e["file"], (d if d and os.path.isdir(d) else default_dir)
    return None, default_dir


def find_associated_cpp(header_path, entries):
    stem = os.path.splitext(os.path.basename(header_path))[0]
    header_dir = os.path.dirname(header_path)
    candidates = []
    for e in entries:
        f = e["file"]
        if not f.endswith((".cpp", ".cc")):
            continue
        if os.path.splitext(os.path.basename(f))[0] == stem:
            candidates.append((e["command"], f))
    if not candidates:
        return None, None
    for cmd, f in candidates:
        if os.path.dirname(f) == header_dir:
            return cmd, f
    candidates.sort(key=lambda cf: len(cf[1]))
    return candidates[0]


def find_unity_associated_cpp(header_path, entries):
    """CMake's UNITY_BUILD merges several .cpp files of a target into one
    generated `Unity/unity_N_cxx.cxx` that #includes each original source -
    the original .cpp then has NO compile_commands.json entry of its own, so
    find_associated_cpp() never finds it even though it exists on disk right
    next to the header (this codebase does this for several test-double
    libraries, e.g. e1ap_test_doubles). Look for a real .cpp with the
    header's basename in the header's own directory, then find a Unity
    source that #includes it, and use THAT entry's compile command - the
    header and its real .cpp are what get edited, never the generated file."""
    stem = os.path.splitext(os.path.basename(header_path))[0]
    header_dir = os.path.dirname(header_path)
    cpp_path = os.path.join(header_dir, stem + ".cpp")
    if not os.path.isfile(cpp_path):
        cpp_path = os.path.join(header_dir, stem + ".cc")
        if not os.path.isfile(cpp_path):
            return None, None

    for e in entries:
        f = e["file"]
        if "/unity/" not in f.lower():
            continue
        try:
            with open(f, errors="replace") as unity_f:
                content = unity_f.read()
        except OSError:
            continue
        if cpp_path in content:
            return e["command"], cpp_path
    return None, None


def sanitize_command(cmd, iwyu_bin, check_also=None):
    # shlex, not split(" "): compile_commands.json commands carry quoted arguments
    # (-DFOO="a b") that a naive split tears in half, and runs of spaces that turn
    # into empty argv entries clang then rejects.
    parts = shlex.split(cmd)
    out = [iwyu_bin]
    skip_next = False
    for p in parts[1:]:
        if skip_next:
            skip_next = False
            continue
        if p == "-o":
            skip_next = True
            continue
        if p in ("-c", "-Werror"):
            continue
        if any(p.startswith(pfx) for pfx in _BAD_GCC_FLAGS_PREFIXES):
            continue
        out.append(p)
    out.append("-Wno-unknown-warning-option")
    out.append("-Xiwyu")
    out.append("--max_line_length=120")
    # A single path or a list: unity mode needs IWYU to report on both the header
    # AND its real .cpp, neither of which IWYU can auto-associate with the
    # generated Unity/unity_N_cxx.cxx main file by filename matching.
    for pattern in ([check_also] if isinstance(check_also, str) else (check_also or [])):
        out.append("-Xiwyu")
        out.append(f"--check_also={pattern}")
    return out


def run(cmd_list, cwd, timeout=120):
    return subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout, cwd=cwd)


# Dependency-file generation must be stripped from a measurement run, not merely
# tolerated: -MF names a path inside the build tree, so preprocessing with it
# rewrites the .d file Ninja relies on for incremental correctness.
_DEP_FLAGS = ("-MD", "-MMD", "-MP", "-MG")
_DEP_FLAGS_WITH_ARG = ("-MT", "-MF", "-MQ", "-MJ")


def preprocess_command(cmd):
    """Turn a compile_commands.json command into a preprocess-only one.

    argv[0] is kept deliberately - unlike sanitize_command, which swaps in the
    IWYU binary. The number worth measuring is what the project's own compiler
    parses, and `-E -P` is spelled identically by gcc and clang, so measuring
    needs no clang of its own on a gcc build. -P matters as much as -E: without
    it the output is padded with linemarkers, which have no parse cost but would
    dominate the count."""
    parts = shlex.split(cmd)
    out = [parts[0]]
    skip_next = False
    for p in parts[1:]:
        if skip_next:
            skip_next = False
            continue
        if p == "-o" or p in _DEP_FLAGS_WITH_ARG:
            skip_next = True
            continue
        # Glued spelling (-MFpath) takes its argument with it.
        if any(p.startswith(f) for f in _DEP_FLAGS_WITH_ARG):
            continue
        if p in ("-c", "-Werror") or p in _DEP_FLAGS:
            continue
        out.append(p)
    out.extend(["-E", "-P"])
    return out


def preprocessed_line_count(cmd, cwd, timeout):
    """Lines the preprocessor hands the parser for this TU, or None.

    Every failure path returns None. The measurement is diagnostic only, so it
    must never be able to fail a header that the real cleanup handled fine."""
    try:
        proc = subprocess.Popen(preprocess_command(cmd), cwd=cwd,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, ValueError, IndexError):
        return None
    # Streamed rather than captured: a preprocessed TU of this kind runs to tens
    # of millions of bytes and only the line total is wanted. The deadline is
    # checked per chunk so a wedged compiler can't outlive the batch runner's
    # own backstop, which would cost this header its result line.
    deadline = time.monotonic() + timeout
    lines = 0
    try:
        with proc.stdout as out:
            while True:
                chunk = out.read(1 << 20)
                if not chunk:
                    break
                lines += chunk.count(b"\n")
                if time.monotonic() > deadline:
                    proc.kill()
                    return None
        if proc.wait(timeout=max(1, int(deadline - time.monotonic()))) != 0:
            return None
    except (subprocess.TimeoutExpired, OSError):
        proc.kill()
        return None
    return lines


def record_closure(result, args, cmd, cwd, measured_tu, before, unchanged=False):
    """Attach the before/after preprocessed-line delta to a result line."""
    if not args.measure_closure:
        return
    entry = {"tu": measured_tu}
    after = before if unchanged else (
        preprocessed_line_count(cmd, cwd, args.measure_timeout) if before is not None else None)
    if before is None or after is None:
        entry["detail"] = "preprocess-only measurement failed or timed out"
    else:
        entry.update({"before": before, "after": after, "saved": before - after})
    result["closure"] = entry


def parse_sections(text):
    """Line-based parse of IWYU output into
    {filename: {"add": [lines], "remove": [lines]}} - far more robust
    than regexing the whole blob, since section bodies can be empty and
    file paths can contain regex-special characters."""
    sections = {}
    current_file = None
    current_kind = None
    for line in text.split("\n"):
        stripped = line.rstrip()
        m_add = _ADD_HEADER_RE.match(stripped)
        m_rm = _REMOVE_HEADER_RE.match(stripped)
        m_tot = _TOTAL_HEADER_RE.match(stripped)
        if m_add:
            current_file = m_add.group(1)
            current_kind = "add"
            sections.setdefault(current_file, {"add": [], "remove": []})
            continue
        if m_rm:
            current_file = m_rm.group(1)
            current_kind = "remove"
            sections.setdefault(current_file, {"add": [], "remove": []})
            continue
        if m_tot or _SECTION_END_RE.match(stripped):
            current_file = None
            current_kind = None
            continue
        if current_file and current_kind and stripped:
            sections[current_file][current_kind].append(stripped)
    return sections


def strip_comments_and_strings(src):
    """Blank out //... line comments, /*...*/ block comments, and string/char
    literal contents (replacing with spaces, preserving length/newlines) so a
    plain substring search for a symbol name doesn't get fooled by a mention
    inside a comment or a string literal. Real incident: byte_buffer_view.h
    got a forward-declare for `byte_buffer` that only ever appears in
    comments ("Conversion from byte_buffer-like type...") - never in actual
    code - because the naive substring check treated the comment mention as
    real usage."""
    out = []
    i, n = 0, len(src)
    state = None  # None | "line_comment" | "block_comment" | "string" | "char"
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state == "line_comment":
            if c == "\n":
                state = None
                out.append(c)
            else:
                out.append(" ")
            i += 1
            continue
        if state == "block_comment":
            if c == "*" and nxt == "/":
                out.append("  ")
                i += 2
                state = None
                continue
            out.append(c if c == "\n" else " ")
            i += 1
            continue
        if state in ("string", "char"):
            end_ch = '"' if state == "string" else "'"
            if c == "\\" and i + 1 < n:
                out.append("  ")
                i += 2
                continue
            if c == end_ch:
                state = None
                out.append(" ")
                i += 1
                continue
            out.append(c if c == "\n" else " ")
            i += 1
            continue
        # state is None
        if c == "/" and nxt == "/":
            state = "line_comment"
            out.append("  ")
            i += 2
            continue
        if c == "/" and nxt == "*":
            state = "block_comment"
            out.append("  ")
            i += 2
            continue
        if c == '"':
            state = "string"
            out.append(c)
            i += 1
            continue
        if c == "'":
            state = "char"
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def drop_dead_forward_declares(text):
    """A forward-declare IWYU wants to add to file F can be a false
    positive: if some OTHER file in the checked TU instantiates F's own
    template with a type T, IWYU can misattribute the need for T's
    forward-declare back to F itself, even though F's body never
    references T at all. Drop any add-line whose declared symbol never
    appears anywhere else in that specific file's current on-disk
    content OUTSIDE of comments/string literals - a real usage always
    leaves the bare name somewhere in the file's actual code, so its
    total absence there (even if it's mentioned in a comment) means the
    suggestion is spurious."""
    lines = text.split("\n")
    out = []
    current_file = None
    in_add = False
    file_body_cache = {}

    def body_of(path):
        if path not in file_body_cache:
            try:
                with open(path) as f:
                    file_body_cache[path] = strip_comments_and_strings(f.read())
            except OSError:
                file_body_cache[path] = ""
        return file_body_cache[path]

    for line in lines:
        stripped = line.rstrip()
        m_add = _ADD_HEADER_RE.match(stripped)
        m_rm = _REMOVE_HEADER_RE.match(stripped)
        m_tot = _TOTAL_HEADER_RE.match(stripped)
        if m_add:
            current_file = m_add.group(1)
            in_add = True
            out.append(line)
            continue
        if m_rm:
            current_file = m_rm.group(1)
            in_add = False
            out.append(line)
            continue
        if m_tot:
            current_file = m_tot.group(1)
            in_add = False
            out.append(line)
            continue

        if in_add and current_file:
            syms = _FWD_DECL_SYMBOL_RE.findall(line) + _FWD_DECL_ENUM_RE.findall(line)
            if syms:
                body = body_of(current_file)
                bare_names = [s.rsplit("::", 1)[-1] for s in syms]
                if not any(re.search(r"\b" + re.escape(n) + r"\b", body) for n in bare_names):
                    continue
        out.append(line)
    return "\n".join(out)


def format_files(paths, clang_format_bin, cwd):
    """Best-effort reformat of files fix_include already rewrote. Formatting is
    cosmetic and runs after the edits are on disk, so a missing or failing
    formatter must never take down the result line describing those edits."""
    failed = []
    for p in paths:
        try:
            proc = subprocess.run([clang_format_bin, "-i", p], cwd=cwd, capture_output=True, text=True)
        except OSError as e:
            failed.append(f"{p}: {e}")
            continue
        if proc.returncode != 0:
            failed.append(f"{p}: {proc.stderr.strip()[-200:]}")
    return failed


# Pre-run content of every file the targeted level is allowed to mutate, so an
# abort at ANY point (give-up, dry-run, crash, or the batch runner's hard
# timeout) puts the tree back exactly as found. A file left half-migrated is
# strictly worse than one never attempted.
_BACKUPS = {}


def take_backups(paths):
    _BACKUPS.clear()
    for p in paths:
        if p and os.path.isfile(p):
            with open(p) as f:
                _BACKUPS[p] = f.read()


def restore_backups():
    for p, content in _BACKUPS.items():
        try:
            with open(p) as f:
                if f.read() == content:
                    continue
        except OSError:
            pass
        with open(p, "w") as f:
            f.write(content)


def restore_whitespace_only_changes():
    """Put back the pre-run content of any file whose only remaining difference
    is blank lines. Removing an include and adding it straight back can shift
    the surrounding blank lines; a pure-whitespace hunk is noise in a cleanup
    diff that otherwise says nothing changed."""
    for p, content in _BACKUPS.items():
        try:
            with open(p) as f:
                current = f.read()
        except OSError:
            continue
        if current == content:
            continue
        if [l for l in current.split("\n") if l.strip()] == [l for l in content.split("\n") if l.strip()]:
            with open(p, "w") as f:
                f.write(content)


def files_unchanged_since_backup():
    for p, content in _BACKUPS.items():
        try:
            with open(p) as f:
                if f.read() != content:
                    return False
        except OSError:
            return False
    return True


_RELEVANT_LINE_RE = re.compile(
    r"^\s*#\s*include\b|^\s*(?:class|struct|enum|union)\b.*[;{]\s*$|^\s*template\s*<")


def actual_include_diff(pre_text, post_text):
    """The #include and forward-declare/enum/class lines that genuinely
    differ between a file's pre-run backup and its FINAL content - after
    fix_include, remove_fragile_forward_declares, upgrade_cpp_forward_declares
    and (at targeted level) the compile-verified repair loop have all had
    their say.

    This exists because `removed_lines`/`added_lines` are recorded from the
    raw IWYU suggestion BEFORE any of that later fixup runs - accurate as a
    statement of what was asked for, not of what actually ended up on disk.
    Reviewing a batch's results file against the stale suggestion is what
    made manually cross-checking nearly every "CHANGED" entry against `git
    diff` necessary in practice; this makes the JSON itself trustworthy
    on its own.

    Line-based, not a real diff: a multi-line template forward-declare span
    can show only one of its physical lines. Good enough as a review aid
    while a full multi-line diff isn't worth the complexity here."""
    def relevant_lines(text):
        return [line.strip() for line in text.split("\n") if _RELEVANT_LINE_RE.match(line)]

    pre_counts = Counter(relevant_lines(pre_text))
    post_counts = Counter(relevant_lines(post_text))
    removed = sorted((pre_counts - post_counts).elements())
    added = sorted((post_counts - pre_counts).elements())
    return removed, added


def _install_abort_restore():
    def handler(signum, _frame):
        restore_backups()
        os._exit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("header")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--level", choices=["remove", "forward-declare", "targeted", "explicit"], default="remove")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--default-fallback-tu", default=None)
    ap.add_argument("--deps-dump", default=None,
                     help="path to a pre-generated `ninja -t deps` dump (see dump_ninja_deps.py). "
                          "Generate it once per run; see find_fallback_tu.py for why per-header "
                          "regeneration causes spurious failures.")
    ap.add_argument("--iwyu-bin", default="include-what-you-use")
    ap.add_argument("--fix-include-bin", default="fix_include")
    ap.add_argument("--clang-format-bin", default="clang-format-18")
    ap.add_argument("--iwyu-timeout", type=int, default=120,
                     help="seconds to allow IWYU per header. Keep run_batch.sh's own per-header "
                          "timeout strictly above this, so an IWYU overrun is reported as such "
                          "rather than killed from outside as an unexplained hang.")
    ap.add_argument("--validate-rounds", type=int, default=3,
                     help="targeted level only: how many recompile+repair rounds to allow before "
                          "giving up and restoring the file. More than one is needed because the "
                          "first missing symbol's error can mask the next.")
    ap.add_argument("--measure-closure", action="store_true",
                     help="preprocess the checked TU before and after the edits and report the "
                          "line-count delta. Costs two preprocess-only runs per changed header; "
                          "the batch runner's hard timeout must cover them.")
    ap.add_argument("--measure-timeout", type=int, default=120,
                     help="seconds per preprocess-only measurement run.")
    ap.add_argument("--validate-timeout", type=int, default=None,
                     help="targeted level only: seconds per validation recompile (defaults to "
                          "--iwyu-timeout). The batch runner's hard timeout must exceed "
                          "--iwyu-timeout + --validate-rounds x this.")
    return ap.parse_args()


def process(args):
    # IWYU's own output and compile_commands.json always use absolute paths - a
    # relative header path matches nothing downstream and silently looks like
    # every check failed ("not mentioned in iwyu output", "no fallback TU could
    # be resolved"), which reads as tool flakiness but is really just this.
    header_path = os.path.abspath(os.path.join(args.repo, args.header))
    entries = load_compile_commands(args.build_dir)
    assoc_cmd, assoc_cpp_path = find_associated_cpp(header_path, entries)

    if assoc_cmd is None:
        assoc_cmd, assoc_cpp_path = find_unity_associated_cpp(header_path, entries)
        unity_mode = assoc_cmd is not None
    else:
        unity_mode = False

    if assoc_cmd is not None:
        check_also = [header_path, assoc_cpp_path] if unity_mode else None
        cmd_list = sanitize_command(assoc_cmd, args.iwyu_bin, check_also=check_also)
        mode = "unity_associated_cpp" if unity_mode else "associated_cpp"
        # IWYU may legitimately want to fix both the header and its own .cpp together.
        files_to_modify = [header_path, assoc_cpp_path]
        raw_cmd = assoc_cmd
    else:
        find_fallback_cmd = ["python3", FIND_FALLBACK_SCRIPT, header_path, args.build_dir,
                             args.default_fallback_tu or "", "--repo-root", os.path.abspath(args.repo)]
        if args.deps_dump:
            find_fallback_cmd.extend(["--deps-dump", args.deps_dump])
        fallback_proc = subprocess.run(find_fallback_cmd, capture_output=True, text=True)
        fallback_tu = fallback_proc.stdout.strip()
        if not fallback_tu:
            print(json.dumps({"header": header_path, "status": "skipped",
                               "detail": "no associated .cpp and no fallback TU could be resolved"}))
            return
        fallback_cmd = None
        for e in entries:
            if e["file"] == fallback_tu:
                fallback_cmd = e["command"]
                break
        if fallback_cmd is None:
            print(json.dumps({"header": header_path, "status": "skipped",
                               "detail": f"fallback TU {fallback_tu} not found in compile_commands.json"}))
            return
        cmd_list = sanitize_command(fallback_cmd, args.iwyu_bin, check_also=header_path)
        mode = "fallback_check_also"
        # The fallback TU is only a vehicle to get IWYU to check header_path - never
        # apply whatever IWYU separately found for the fallback TU/its own header.
        files_to_modify = [header_path]
        raw_cmd = fallback_cmd

    try:
        proc = run(cmd_list, cwd=args.repo, timeout=args.iwyu_timeout)
    except subprocess.TimeoutExpired:
        print(json.dumps({"header": header_path, "status": "skipped", "mode": mode,
                           "detail": f"iwyu timeout after {args.iwyu_timeout}s"}))
        return
    if proc.returncode != 0:
        print(json.dumps({"header": header_path, "status": "skipped", "mode": mode,
                           "detail": "iwyu compile error",
                           "stderr_tail": proc.stderr[-1500:]}))
        return

    raw = proc.stderr
    if header_path not in raw:
        print(json.dumps({"header": header_path, "status": "skipped", "mode": mode,
                           "detail": "header not mentioned in iwyu output (not reached/associated in this TU)"}))
        return

    targeted = args.level == "targeted"
    # For a header target, targeted applies exactly the forward-declare level's
    # edits, then proves them by recompiling and repairs only what genuinely
    # broke (see targeted_repair.py). For a .cpp target, strip_iwyu_output.py's
    # targeted level adds nothing at all here - see its own docstring - so every
    # addition for a .cpp comes only from the compile-verified repair loop below.
    strip_proc = subprocess.run(["python3", STRIP_SCRIPT, "--level", args.level], input=raw,
                                 capture_output=True, text=True)
    # An empty stdout from a crashed filter parses as "IWYU suggested nothing", i.e. a
    # clean no_change for every header in the batch.
    if strip_proc.returncode != 0:
        print(json.dumps({"header": header_path, "status": "skipped", "mode": mode,
                           "detail": f"strip_iwyu_output failed: {strip_proc.stderr.strip()[-500:]}"}))
        return
    stripped = drop_dead_forward_declares(strip_proc.stdout)

    sections = parse_sections(stripped)
    header_section = sections.get(header_path, {"add": [], "remove": []})
    removed_lines = header_section["remove"]
    added_lines = header_section["add"]

    if not removed_lines and not added_lines:
        print(json.dumps({"header": header_path, "status": "no_change", "mode": mode}))
        return

    # Measured only once there is an edit to attribute a delta to, and while the
    # tree is still pre-edit. A non-targeted dry-run never writes, so there would
    # be no "after" to compare against.
    measure = args.measure_closure and not (args.dry_run and not targeted)
    measured_tu, tu_dir = tu_for_command(entries, raw_cmd, args.repo) if measure else (None, args.repo)
    closure_before = preprocessed_line_count(raw_cmd, tu_dir, args.measure_timeout) if measure else None

    # Taken unconditionally (not just at targeted level) so actual_include_diff
    # below can report what really changed on disk, not just what was asked
    # for - see its own docstring.
    take_backups(files_to_modify)
    if targeted:
        # The validation recompile can only read the real files, so a targeted
        # dry-run edits them for real and restores them before returning.
        _install_abort_restore()

    fix_args = [args.fix_include_bin, "--nosafe_headers", "--noreorder", "--nocomments"]
    if args.dry_run and not targeted:
        fix_args.append("--dry_run")
    fix_args.extend(f for f in files_to_modify if f)
    fix_proc = subprocess.run(fix_args, input=stripped, capture_output=True, text=True, cwd=args.repo)

    result = {"header": header_path, "status": "removed" if removed_lines else "added", "mode": mode,
              "removed_lines": removed_lines, "added_lines": added_lines,
              "fix_include_output": fix_proc.stdout[-2000:]}

    # Surfaced rather than treated as failure: some fix_include builds exit with the count
    # of files they changed. Compare against touched_files before reading it as an error.
    if fix_proc.returncode != 0:
        result["fix_include_rc"] = fix_proc.returncode
        result["fix_include_stderr"] = fix_proc.stderr.strip()[-500:]

    # In associated_cpp mode the .cpp is edited alongside the header, and reverting a
    # broken header without its .cpp half leaves a dangling mutation that resurfaces as
    # a mystery failure in a later batch (SKILL.md phase 3, step 5). Record those edits
    # here so the revert has something to work from.
    other_changes = {f: sections[f] for f in files_to_modify
                     if f and f != header_path and f in sections
                     and (sections[f]["add"] or sections[f]["remove"])}
    if other_changes:
        result["other_file_changes"] = other_changes

    if targeted:
        report = targeted_repair.repair(
            cmd_list, args.repo, files_to_modify, raw, strip_comments_and_strings,
            pre_run_contents=dict(_BACKUPS), rounds=args.validate_rounds,
            timeout=args.validate_timeout or args.iwyu_timeout,
            formatter=lambda paths: format_files(paths, args.clang_format_bin, args.repo))
        if report["additions"]:
            result["targeted_additions"] = report["additions"]
        if report["dropped_forward_declares"]:
            result["targeted_dropped_forward_declares"] = report["dropped_forward_declares"]
        result["validation_rounds"] = report["rounds"]
        if not report["ok"]:
            restore_backups()
            print(json.dumps({"header": header_path, "status": "skipped", "mode": mode,
                               "detail": "targeted: " + (report["reason"] or "validation failed"),
                               "reverted_to_pre_run_content": sorted(_BACKUPS),
                               "attempted_removed_lines": removed_lines,
                               "attempted_added_lines": added_lines,
                               "attempted_targeted_additions": report["additions"],
                               "validation_rounds": report["rounds"],
                               "stderr_tail": report["stderr_tail"][-1000:]}))
            return
        de_fragiled = targeted_repair.remove_fragile_forward_declares(
            cmd_list, args.repo, files_to_modify, raw, strip_comments_and_strings)
        if de_fragiled:
            result["fragile_forward_declares_removed"] = de_fragiled
        upgraded = targeted_repair.upgrade_cpp_forward_declares(
            cmd_list, args.repo, files_to_modify, raw, strip_comments_and_strings)
        if upgraded:
            result["cpp_forward_declares_upgraded"] = upgraded
        touched = sorted(set(re.findall(r">>> Fixing #includes in '([^']+)'", fix_proc.stdout))
                         | set(report["additions"]) | set(upgraded) | set(de_fragiled))
        format_failures = format_files(touched, args.clang_format_bin, args.repo)
        if format_failures:
            result["clang_format_failures"] = format_failures
        result["touched_files"] = touched
        restore_whitespace_only_changes()
        # A removal that the repair step had to put straight back leaves the file
        # byte-identical: report that honestly instead of claiming a change.
        if files_unchanged_since_backup():
            result["status"] = "no_change"
            result["detail"] = "targeted: every removal was restored by the validation repair"
        # Ahead of the dry-run restore below, so the edits being measured are the
        # ones still on disk.
        record_closure(result, args, raw_cmd, tu_dir, measured_tu, closure_before,
                       unchanged=result["status"] == "no_change")
        if args.dry_run:
            restore_backups()
            result["dry_run"] = True
    elif not args.dry_run:
        de_fragiled = targeted_repair.remove_fragile_forward_declares(
            cmd_list, args.repo, files_to_modify, raw, strip_comments_and_strings)
        if de_fragiled:
            result["fragile_forward_declares_removed"] = de_fragiled
        upgraded = targeted_repair.upgrade_cpp_forward_declares(
            cmd_list, args.repo, files_to_modify, raw, strip_comments_and_strings)
        if upgraded:
            result["cpp_forward_declares_upgraded"] = upgraded
        touched = sorted(set(re.findall(r">>> Fixing #includes in '([^']+)'", fix_proc.stdout))
                         | set(upgraded) | set(de_fragiled))
        result["touched_files"] = touched
        format_failures = format_files(touched, args.clang_format_bin, args.repo)
        if format_failures:
            result["clang_format_failures"] = format_failures
        record_closure(result, args, raw_cmd, tu_dir, measured_tu, closure_before)

    # A dry-run at any level restores (or, for the non-targeted case, never even
    # writes) the file, so there is deliberately nothing "actual" to report there.
    if header_path in _BACKUPS and not args.dry_run and result["status"] != "skipped":
        try:
            with open(header_path) as f:
                current_text = f.read()
        except OSError:
            current_text = _BACKUPS[header_path]
        actual_removed, actual_added = actual_include_diff(_BACKUPS[header_path], current_text)
        if actual_removed:
            result["actual_removed_lines"] = actual_removed
        if actual_added:
            result["actual_added_lines"] = actual_added
        # `status` was set from the raw pre-repair suggestion, before
        # remove_fragile_forward_declares/upgrade_cpp_forward_declares/the
        # compile-verified repair loop all had their say - any of them can
        # reconcile a removal straight back (a real incident: a header's
        # `dmrs.h`/`rnti.h`/`ldpc_base_graph.h` removals all got individually
        # restored while an unrelated forward-declare got upgraded to a real
        # #include, netting to an ADD with no net REMOVE at all, yet `status`
        # still read "removed"). Recompute it from what's actually different
        # on disk - same "removed wins on a tie" rule the original guess used,
        # so the vocabulary stays exactly {removed, added, no_change, skipped}.
        if actual_removed:
            result["status"] = "removed"
        elif actual_added:
            result["status"] = "added"
        else:
            result["status"] = "no_change"

    print(json.dumps(result))


def main():
    args = parse_args()
    try:
        process(args)
    except Exception as e:
        # Every header must produce exactly one JSON line. An uncaught exception here
        # would drop the header from the results file entirely - indistinguishable from
        # a header that was never attempted, and worse after fix_include has already
        # written to disk.
        restore_backups()
        print(json.dumps({"header": os.path.abspath(os.path.join(args.repo, args.header)),
                          "status": "skipped", "detail": f"{type(e).__name__}: {e}"}))


if __name__ == "__main__":
    main()
