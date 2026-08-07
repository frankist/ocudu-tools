#!/usr/bin/env python3

"""
header_line_cost.py - Rank headers by how many source lines they cost the build.

Cost model:

    cost(header) = lines(header) x TUs whose include closure contains it

A header is counted ONCE per translation unit no matter how many paths reach
it, because the include guard makes every reach after the first free. So the
figure answers "if this header vanished, how many lines would the compiler stop
reading, summed over the whole build" - which is what makes it a ranking of
worst offenders rather than a popularity contest: a 12-line header in 4000 TUs
and a 4000-line header in 12 TUs score the same.

Reads the include graph emitted by gen_dependency_tree.py and the TU list from
compile_commands.json. Writes <build_dir>/header_line_cost.json, headers sorted
by descending cost.

What the number is and is not:
  - It is a static estimate, in physical lines, of a header's total weight
    across the build. Use it to pick where to point a cleanup sweep.
  - It is NOT a measurement of what any particular edit saved. Lines are not
    uniformly expensive (a template-heavy line costs far more than a #define)
    and the estimate cannot see the preprocessor. For the ground truth on a
    specific edit, use run_batch.sh's closure measurement, which preprocesses
    the real TU - see SKILL.md, "Measuring the win".
  - Headers outside the scanned source roots (system and third-party headers)
    are LEAF nodes: they are counted themselves, but nothing they include is
    reachable, so their own cost is right while everything beneath them is
    missing entirely. They are marked "external": true.

Usage:
  python3 header_line_cost.py [options]

Options:
  --repo <path>              Project root. Default: git toplevel of the cwd.
  --tree <path>              Dependency tree YAML from gen_dependency_tree.py.
                             Default: <build-dir>/ocudu_dependency_tree.yml.
  --compile-commands <path>  compile_commands.json, or the build directory
                             holding it. Default: <repo>/build/compile_commands.json.
  --output <path>            Output file. Default: <build-dir>/header_line_cost.json.
  --top <n>                  Rows to print to stderr. Default: 25. 0 prints none.
  --repo-only                Drop external headers from the output.
  --quiet                    Suppress the summary and the table.

Exit codes:
  0  ranking written
  2  bad input (missing tree, missing compile_commands.json, no TUs resolved)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

try:
    import yaml
except ImportError:
    sys.stderr.write("error: PyYAML required: pip install pyyaml\n")
    sys.exit(2)

LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

HEADER_SUFFIXES = {".h", ".hpp", ".hh", ".hxx", ".inc", ".ipp", ".tpp", ""}


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


def resolve_compile_commands(repo: Path, given: str | None) -> Path:
    if given:
        path = Path(given)
        if path.is_dir():
            path = path / "compile_commands.json"
    else:
        path = repo / "build" / "compile_commands.json"
    if not path.is_file():
        fail(f"{path}: no such compile_commands.json")
    return path.resolve()


def is_header(rel_path: str) -> bool:
    """Extensionless names count: the C++ standard library spells every header
    that way (<vector>, <memory>), and those are exactly the ones a cost
    ranking must not silently drop."""
    return Path(rel_path).suffix.lower() in HEADER_SUFFIXES


def load_tree(tree_path: Path) -> tuple[dict[str, list[str]], dict]:
    try:
        doc = yaml.load(tree_path.read_text(encoding="utf-8"), Loader=LOADER)
    except OSError as exc:
        fail(f"{tree_path}: {exc}\nGenerate it first with gen_dependency_tree.py.")
    except yaml.YAMLError as exc:
        fail(f"{tree_path}: {exc}")
    if not isinstance(doc, dict) or "files" not in doc:
        fail(f"{tree_path}: not a dependency tree (no 'files' key)")
    edges = {path: (entry or {}).get("includes", []) for path, entry in doc["files"].items()}
    return edges, doc.get("meta", {})


def tu_paths(cc_path: Path, repo: Path) -> list[str]:
    """Repo-relative paths of every TU the build actually compiles."""
    try:
        entries = json.loads(cc_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{cc_path}: {exc}")
    out, seen = [], set()
    for entry in entries:
        raw = entry.get("file")
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = Path(entry.get("directory", cc_path.parent)) / path
        try:
            resolved = path.resolve()
        except OSError:
            continue
        try:
            key = resolved.relative_to(repo).as_posix()
        except ValueError:
            key = resolved.as_posix()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def closure(start: str, edges: dict[str, list[str]]) -> set[str]:
    """Every file reachable from start, the start itself excluded.

    A plain visited-set walk, so a header reached by twelve different paths is
    in the result once - the include-guard semantics the cost model needs - and
    the include cycles that forward-declaration patterns create terminate
    instead of recursing forever."""
    seen: set[str] = set()
    stack = list(edges.get(start, ()))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, ()))
    seen.discard(start)
    return seen


def count_lines(path: Path) -> int | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--repo")
    parser.add_argument("--tree")
    parser.add_argument("--compile-commands")
    parser.add_argument("--output")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--repo-only", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve() if args.repo else git_toplevel()
    if repo is None:
        fail("not inside a git repository; pass --repo <path>")
    if not repo.is_dir():
        fail(f"{repo}: no such directory")

    cc_path = resolve_compile_commands(repo, args.compile_commands)
    build_dir = cc_path.parent
    tree_path = Path(args.tree) if args.tree else build_dir / "ocudu_dependency_tree.yml"
    output = Path(args.output) if args.output else build_dir / "header_line_cost.json"

    edges, tree_meta = load_tree(tree_path.resolve())
    tus = tu_paths(cc_path, repo)
    if not tus:
        fail(f"{cc_path}: no translation units")

    # A TU absent from the tree contributes nothing, so the totals below would
    # quietly understate every header it reaches. Generated sources are the
    # usual cause - the tree deliberately skips build directories, which is
    # also where CMake puts unity chunks and protobuf output.
    known = [tu for tu in tus if tu in edges]
    missing = len(tus) - len(known)

    tu_counts: dict[str, int] = {}
    for tu in known:
        for node in closure(tu, edges):
            if is_header(node):
                tu_counts[node] = tu_counts.get(node, 0) + 1

    rows = []
    unreadable = 0
    for path, count in tu_counts.items():
        absolute = Path(path) if Path(path).is_absolute() else repo / path
        external = not str(absolute).startswith(str(repo) + "/")
        if external and args.repo_only:
            continue
        lines = count_lines(absolute)
        if lines is None:
            unreadable += 1
            continue
        row = {"path": path, "lines": lines, "tu_count": count, "cost": lines * count}
        if external:
            row["external"] = True
        rows.append(row)

    rows.sort(key=lambda r: (-r["cost"], -r["tu_count"], r["path"]))

    doc = {
        "meta": {
            "repo_root": repo.as_posix(),
            "compile_commands": cc_path.as_posix(),
            "dependency_tree": tree_path.resolve().as_posix(),
            "tu_count": len(known),
            "tus_missing_from_tree": missing,
            "header_count": len(rows),
            "unreadable_headers": unreadable,
            "total_cost": sum(r["cost"] for r in rows),
            "tree_unresolved_includes": tree_meta.get("unresolved_count"),
            "cost_model": "lines(header) x TUs reaching it, counted once per TU",
        },
        "headers": rows,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")

    if args.quiet:
        return 0

    sys.stderr.write(
        f"{output}: {len(rows)} headers over {len(known)} TUs, "
        f"total cost {doc['meta']['total_cost']:,} lines\n"
    )
    if missing:
        sys.stderr.write(f"warning: {missing} TUs are absent from the tree and were not counted\n")
    if tree_meta.get("unresolved_count"):
        sys.stderr.write(
            f"warning: the tree has {tree_meta['unresolved_count']} unresolved includes; "
            f"edges it could not resolve are missing from every closure below\n")
    if args.top > 0:
        sys.stderr.write(f"\n{'COST':>12}  {'LINES':>7}  {'TUS':>6}  PATH\n")
        for row in rows[:args.top]:
            mark = " (external)" if row.get("external") else ""
            sys.stderr.write(
                f"{row['cost']:>12,}  {row['lines']:>7,}  {row['tu_count']:>6,}  {row['path']}{mark}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
