#!/usr/bin/env bash
# List every header (.h/.hpp) under a target directory, one absolute path
# per line, excluding vendored/external code. This is the work-list the
# skill cleans up - note it does NOT include headers outside the target
# directory that might also need fixing as a side effect (consumer files
# relying on a removed transitive include); those are discovered later,
# during rebuild-driven root-causing (see SKILL.md phase 3).
set -u

# Always resolve to an absolute path, however target_dir was given -
# every consumer of this list (process_header.py, IWYU's own output,
# compile_commands.json) deals exclusively in absolute paths. A relative
# path here silently produces a work-list that matches nothing downstream
# - every header looks "not mentioned in iwyu output" / "no fallback TU
# could be resolved", which reads as tool flakiness but is really just
# this.
TARGET_DIR="$(cd "$1" && pwd)"

find "$TARGET_DIR" -type f \( -name '*.h' -o -name '*.hpp' \) \
  -not -path '*/external/*' \
  | sort
