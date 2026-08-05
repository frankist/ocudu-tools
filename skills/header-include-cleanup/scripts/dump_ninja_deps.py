#!/usr/bin/env python3
"""Generate the `ninja -t deps` dump ONCE and write it to a file, for
find_fallback_tu.py to reuse across an entire batch (or the whole run).
See find_fallback_tu.py's module docstring for why regenerating this
per-header is slow enough to cause spurious "no fallback TU" failures.

Usage: dump_ninja_deps.py <build_dir> <output_path>
"""
import subprocess
import sys


def main():
    build_dir = sys.argv[1]
    output_path = sys.argv[2]
    result = subprocess.run(["ninja", "-C", build_dir, "-t", "deps"], capture_output=True, text=True, timeout=300)
    # A silently empty or partial dump degrades every header in the run to the slower,
    # weaker grep-based fallback-TU search, which then reads as "these headers aren't
    # reachable" instead of "the dump never got written".
    if result.returncode != 0 or not result.stdout.strip():
        sys.stderr.write(f"ninja -t deps failed (rc={result.returncode}) in {build_dir}\n")
        sys.stderr.write(result.stderr[-2000:] + "\n")
        return 1
    with open(output_path, "w") as f:
        f.write(result.stdout)
    print(f"wrote {len(result.stdout)} bytes to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
