#!/usr/bin/env bash
# When a removal breaks a distant consumer file, use this BEFORE deciding
# whether to fix that one consumer or just revert the removal. It answers:
# "how many OTHER files rely on this same transitive path?"
#
# A narrow fanout (1-3 files) is worth fixing properly - add the missing
# direct #include to each real consumer, completing the IWYU cleanup as
# it should be done, rather than backing off the original removal.
#
# A wide fanout (dozens of files) means the header being trimmed is too
# pervasively relied-upon transitively at this codebase's scale to chase
# exhaustively for what's usually a single-line win. Revert the original
# removal instead of touching every consumer.
#
# There's no hard numeric cutoff - use judgment, but single digits is
# "fix it", low tens or more is "not worth it" (seen directly this
# project: task_executor.h had 22+ hidden consumers, async_task.h had 11+
# - both were reverted rather than chased).
#
# Usage: check_fanout.sh <repo_root> <usage_grep_pattern> <direct_include_grep_pattern>
# Example:
#   check_fanout.sh /path/to/repo \
#     'task_executor[ &*]+\w+\.execute\(|_executor\.execute\(' \
#     'include.*executors/task_executor\.h'
set -u

REPO="$1"
USAGE_PATTERN="$2"
INCLUDE_PATTERN="$3"

candidates=$(grep -rlE "$USAGE_PATTERN" "$REPO/lib" "$REPO/tests" --include="*.cpp" --include="*.h" 2>/dev/null | sort -u)
total=$(echo "$candidates" | grep -c . || true)
echo "Files using this symbol: $total"
echo "--- of these, missing a direct include ---"
missing=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  if ! grep -qE "$INCLUDE_PATTERN" "$f"; then
    echo "$f"
    missing=$((missing + 1))
  fi
done <<< "$candidates"
echo "--- $missing file(s) missing the direct include ---"
