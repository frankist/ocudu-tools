#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
# SPDX-License-Identifier: BSD-3-Clause-Open-MPI

"""
gen_dependency_tree.py — Emit the #include graph of a C++ project as YAML.

Scans every source file under the project's source roots and records what each
one includes, resolving each directive against the including file's own
directory first and then the -I/-isystem directories harvested from
compile_commands.json.

The output is a flat adjacency map rather than a nested tree: a nested encoding
would duplicate shared headers thousands of times and cannot represent the
cycles that forward-declaration patterns create.

Direct edges only. Transitive reachability is computed on demand by
check_dependency_rules.py, which reads this file.

Usage:
  python3 gen_dependency_tree.py [options]

Options:
  --repo <path>              Project root. Default: git toplevel of the cwd.
  --compile-commands <path>  compile_commands.json, or the build directory
                             holding it. Default:
                             <repo>/build/compile_commands.json.
  --output <path>            Output file. Default:
                             <build-dir>/ocudu_dependency_tree.yml.
  --roots <dir> [...]        Source roots to scan, repo-relative. Default:
                             every top-level directory holding sources, minus
                             the excludes.
  --exclude <pattern> [...]  Extra top-level names to skip (glob, matched
                             against the directory name).
  --quiet                    Suppress the summary line on stderr.

Exit codes:
  0  tree written
  2  bad input (missing compile_commands.json, unreadable repo, empty scan)
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import NoReturn

try:
    import yaml
except ImportError:
    sys.stderr.write("error: PyYAML required: pip install pyyaml\n")
    sys.exit(2)

DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)

SOURCE_SUFFIXES = {".h", ".hpp", ".hh", ".hxx", ".c", ".cc", ".cpp", ".cxx"}

# Top-level names never scanned for outgoing edges. Third-party and generated
# trees stay valid include *targets* — nobody is going to fix their includes,
# so recording their own dependencies is noise.
DEFAULT_EXCLUDES = (".*", "external", "build", "build*", "cmake-build*", "ccache*", "Testing")

INCLUDE_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*[<"]([^">]+)[>"]', re.MULTILINE)
INCLUDE_DIR_RE = re.compile(r"-(?:I|isystem)\s*(\S+)")


def fail(msg: str) -> NoReturn:
    sys.stderr.write(f"error: {msg}\n")
    sys.exit(2)


def git_toplevel() -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(out) if out else None


def discover_build_dirs(repo: Path) -> list[Path]:
    """Directories directly under the repo that hold a compile_commands.json."""
    found = []
    for entry in sorted(repo.iterdir()):
        if entry.is_dir() and (entry / "compile_commands.json").is_file():
            found.append(entry)
    return found


def resolve_compile_commands(repo: Path, given: str | None) -> Path:
    if given:
        path = Path(given)
        if path.is_dir():
            path = path / "compile_commands.json"
        if not path.is_file():
            fail(f"{path}: no such compile_commands.json")
        return path.resolve()

    default = repo / "build" / "compile_commands.json"
    if default.is_file():
        return default.resolve()

    lines = [f"{default}: not found."]
    candidates = discover_build_dirs(repo)
    if candidates:
        lines.append("Build directories that do have one:")
        for c in candidates:
            mtime = (c / "compile_commands.json").stat().st_mtime
            stamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  {c.relative_to(repo)}/compile_commands.json  ({stamp})")
        lines.append("Re-run with --compile-commands <path> to pick one.")
    else:
        lines.append("No build directory holds one. Generate it with either:")
        lines.append("  cmake --preset default")
        lines.append("  cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON")
    fail("\n".join(lines))


def harvest_include_dirs(cc_path: Path) -> list[Path]:
    """-I/-isystem directories from every compile command, first-seen order.

    Order matters: it is the search order the compiler itself would use, so a
    header shadowed by an earlier -I resolves the same way here.
    """
    try:
        entries = json.loads(cc_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{cc_path}: {exc}")
    dirs: list[Path] = []
    seen: set[str] = set()
    for entry in entries:
        base = Path(entry.get("directory", cc_path.parent))
        argv = entry.get("command")
        if argv is None:
            argv = " ".join(entry.get("arguments", []))
        for raw in INCLUDE_DIR_RE.findall(argv):
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = base / candidate
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            key = str(resolved)
            if key in seen or not resolved.is_dir():
                continue
            seen.add(key)
            dirs.append(resolved)
    return dirs


def pick_roots(repo: Path, given: list[str] | None, excludes: list[str]) -> list[Path]:
    if given:
        roots = []
        for name in given:
            path = repo / name
            if not path.is_dir():
                fail(f"{path}: no such source root")
            roots.append(path)
        return roots

    roots = []
    for entry in sorted(repo.iterdir()):
        if not entry.is_dir():
            continue
        if any(fnmatch.fnmatch(entry.name, pat) for pat in excludes):
            continue
        roots.append(entry)
    return roots


def collect_sources(roots: list[Path]) -> list[Path]:
    files = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix in SOURCE_SUFFIXES and path.is_file():
                files.append(path)
    return files


class Resolver:
    """Resolves include directives to repo-relative paths."""

    def __init__(self, repo: Path, include_dirs: list[Path]):
        self.repo = repo
        self.include_dirs = include_dirs
        self._cache: dict[tuple[str, str], str | None] = {}

    def _to_repo_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.repo).as_posix()
        except ValueError:
            return resolved.as_posix()

    def resolve(self, source: Path, target: str) -> str | None:
        key = (str(source.parent), target)
        if key in self._cache:
            return self._cache[key]
        result = None
        local = source.parent / target
        if local.is_file():
            result = self._to_repo_path(local)
        else:
            for base in self.include_dirs:
                candidate = base / target
                if candidate.is_file():
                    result = self._to_repo_path(candidate)
                    break
        self._cache[key] = result
        return result


def build_tree(repo: Path, files: list[Path], resolver: Resolver) -> tuple[dict, int, int]:
    tree: dict[str, dict] = {}
    edge_count = 0
    unresolved_count = 0
    for path in files:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        includes: set[str] = set()
        unresolved: set[str] = set()
        for target in INCLUDE_RE.findall(text):
            resolved = resolver.resolve(path, target)
            if resolved is None:
                unresolved.add(target)
            else:
                includes.add(resolved)
        entry: dict = {"includes": sorted(includes)}
        if unresolved:
            entry["unresolved"] = sorted(unresolved)
        tree[path.resolve().relative_to(repo).as_posix()] = entry
        edge_count += len(includes)
        unresolved_count += len(unresolved)
    return tree, edge_count, unresolved_count


def warn_if_stale(cc_path: Path, files: list[Path]) -> None:
    """A compile_commands.json older than the newest source may lack the -I
    directories a newly added subtree needs, silently pushing real edges into
    `unresolved`."""
    cc_mtime = cc_path.stat().st_mtime
    newest = None
    for path in files:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
            newest_path = path
    if newest is None or newest <= cc_mtime:
        return
    days = (newest - cc_mtime) / 86400.0
    sys.stderr.write(
        f"warning: {cc_path} is {days:.1f} days older than the newest source "
        f"({newest_path}); its -I directories may be incomplete, which shows up "
        f"as inflated unresolved counts. Reconfigure to refresh it.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--repo")
    parser.add_argument("--compile-commands")
    parser.add_argument("--output")
    parser.add_argument("--roots", nargs="+")
    parser.add_argument("--exclude", nargs="+", default=[])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve() if args.repo else git_toplevel()
    if repo is None:
        fail("not inside a git repository; pass --repo <path>")
    if not repo.is_dir():
        fail(f"{repo}: no such directory")

    cc_path = resolve_compile_commands(repo, args.compile_commands)
    build_dir = cc_path.parent
    output = Path(args.output) if args.output else build_dir / "ocudu_dependency_tree.yml"

    excludes = list(DEFAULT_EXCLUDES) + list(args.exclude)
    if build_dir.parent == repo:
        excludes.append(build_dir.name)

    roots = pick_roots(repo, args.roots, excludes)
    files = collect_sources(roots)
    if not files:
        fail(f"no sources found under {repo} (roots: {[r.name for r in roots]})")

    # Roots that turned out to hold no sources are dropped so `meta.roots`
    # describes what was actually scanned.
    scanned_roots = sorted({
        f.resolve().relative_to(repo).parts[0] for f in files
    })

    include_dirs = harvest_include_dirs(cc_path)
    warn_if_stale(cc_path, files)

    resolver = Resolver(repo, include_dirs)
    tree, edge_count, unresolved_count = build_tree(repo, files, resolver)

    doc = {
        "meta": {
            "repo_root": repo.as_posix(),
            "compile_commands": cc_path.as_posix(),
            "roots": scanned_roots,
            "file_count": len(tree),
            "edge_count": edge_count,
            "unresolved_count": unresolved_count,
        },
        "files": tree,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write("# SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited\n")
        handle.write("# SPDX-License-Identifier: BSD-3-Clause-Open-MPI\n")
        handle.write("# Generated by gen_dependency_tree.py — do not edit.\n")
        yaml.dump(
            doc, handle, Dumper=DUMPER,
            sort_keys=True, default_flow_style=False, width=4096, allow_unicode=True,
        )

    if not args.quiet:
        sys.stderr.write(
            f"{output}: {len(tree)} files, {edge_count} edges, "
            f"{unresolved_count} unresolved (compile_commands: {cc_path})\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
