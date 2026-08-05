#!/usr/bin/env python3
"""Find a reasonable translation unit to check a header through, for
headers that have no associated .cpp of their own (pure type/interface
headers). include-what-you-use only reports for the main compiled file
plus files matched by -Xiwyu --check_also=<glob>, so we need SOME real
.cpp whose compile command reaches the header.

Strategy, in order:
  1. If an incremental Ninja build already exists, `ninja -t deps` dumps
     every already-tracked TU's full dependency list (this works whether
     Ninja stores deps in a binary .ninja_deps file - the common case, no
     per-object .d text files on disk at all - or the build used deps=gcc
     with real .d files; `ninja -t deps` normalizes both). Find any TU
     block that already lists the header, and use its source .cpp - a TU
     we know for certain reaches it, with no need to compile anything to
     check. Prefer the block with the FEWEST total deps (smaller/faster
     TU to re-run IWYU on).

     IMPORTANT: this dump is large (routinely 500k-1M+ lines / tens of MB
     for a project this size) and takes real time to generate AND parse.
     Regenerating it fresh for every single header in a batch is slow
     enough to occasionally blow past subprocess timeouts under normal
     system load, which - since a timeout is caught right alongside "no
     Ninja build" and silently falls through to the next strategy - reads
     as flaky, header-dependent failures ("no fallback TU could be
     resolved" for a header that resolves fine when tried again a moment
     later) rather than the actual cause (regenerating a 44MB dump 30
     times in a batch). Generate the dump ONCE per batch with
     `dump_ninja_deps.py` and pass its path via --deps-dump to every
     header in that batch - see SKILL.md Phase 1.
  2. Otherwise, grep the source tree for the header's basename inside
     .cpp files, and pick the shortest matching path (smaller TU, and
     often a more focused/direct include of the header).
  3. Otherwise, fall back to whatever default TU was passed in - the
     caller should supply one known to compile a broad swath of the
     codebase (e.g. a large integration test file), understanding that it
     may not actually reach every header and this step may report
     "not reached" for headers outside its transitive closure.

Usage: find_fallback_tu.py <header_abs_path> <build_dir> [default_tu_path]
                            [--repo-root <path>] [--deps-dump <path>]
Prints the resolved .cpp absolute path on stdout, or nothing if none found.
"""
import argparse
import os
import subprocess


def _scan_deps_text(header_path, lines_iter):
    best_source = None
    best_count = None
    current_source = None
    current_count = 0
    found_header = False

    def flush():
        nonlocal best_source, best_count
        if found_header and current_source is not None:
            if best_count is None or current_count < best_count:
                best_source, best_count = current_source, current_count

    for line in lines_iter:
        line = line.rstrip("\n")
        if line and not line.startswith(("    ", "\t")) and ":" in line:
            flush()
            current_source, current_count, found_header = None, 0, False
            continue
        if not line.strip():
            flush()
            current_source, current_count, found_header = None, 0, False
            continue
        path = line.strip()
        current_count += 1
        if current_source is None and path.endswith((".cpp", ".cc")):
            current_source = path
        if path == header_path:
            found_header = True
    flush()
    return best_source


def find_via_deps_dump(header_path, deps_dump_path):
    try:
        with open(deps_dump_path, errors="replace") as f:
            best_source = _scan_deps_text(header_path, f)
    except OSError:
        return None
    if best_source and os.path.isfile(best_source):
        return os.path.abspath(best_source)
    return None


def find_via_ninja_deps(header_path, build_dir):
    """Slow path: regenerates the full deps dump on every call. Only used
    when no pre-generated --deps-dump was provided - prefer generating one
    once per batch with dump_ninja_deps.py instead (see module docstring)."""
    try:
        result = subprocess.run(
            ["ninja", "-C", build_dir, "-t", "deps"],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    best_source = _scan_deps_text(header_path, result.stdout.splitlines())
    if best_source and os.path.isfile(best_source):
        return os.path.abspath(best_source)
    return None


def find_via_grep(header_path, repo_root):
    basename = os.path.basename(header_path)
    # Searching a non-existent dir makes grep fail wholesale, so a bad repo root
    # would look like "no TU uses this header" rather than "nothing was searched".
    search_dirs = [d for d in (os.path.join(repo_root, "lib"), os.path.join(repo_root, "tests"))
                   if os.path.isdir(d)] or [repo_root]
    try:
        result = subprocess.run(
            ["grep", "-rl", basename, *search_dirs, "--include=*.cpp"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    candidates = [l for l in result.stdout.splitlines() if l.strip()]
    if not candidates:
        return None
    candidates.sort(key=len)
    return os.path.abspath(candidates[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("header")
    ap.add_argument("build_dir")
    ap.add_argument("default_tu", nargs="?", default=None)
    ap.add_argument("--repo-root", default=None,
                     help="repo root to grep in strategy 2. Inferred as the build dir's parent "
                          "when omitted, which is wrong for nested build dirs (build/relwithdebinfo) "
                          "and silently yields no fallback TU at all, since <build>/lib and "
                          "<build>/tests don't exist.")
    ap.add_argument("--deps-dump", default=None,
                     help="path to a pre-generated `ninja -t deps` dump (see dump_ninja_deps.py). "
                          "Strongly preferred over letting this script regenerate it per-header.")
    args = ap.parse_args()

    build_dir = os.path.abspath(args.build_dir)
    repo_root = args.repo_root or os.path.dirname(build_dir.rstrip("/"))

    tu = None
    if args.deps_dump:
        tu = find_via_deps_dump(args.header, args.deps_dump)
    else:
        tu = find_via_ninja_deps(args.header, build_dir)
    if not tu:
        tu = find_via_grep(args.header, repo_root)
    if not tu:
        tu = args.default_tu or None
    if tu:
        print(tu)


if __name__ == "__main__":
    main()
