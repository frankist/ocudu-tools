#!/usr/bin/env bash
# Process every header listed in $3 (one absolute path per line) through
# process_header.py, appending JSON results to $4. A per-header timeout
# guards against any single header hanging the whole batch.
#
# Usage: run_batch.sh <repo> <build_dir> <batch_file> <results_file> \
#                     [level] [deps_dump] [measure_closure]
#
# IMPORTANT: always invoke this as a real script file run in the
# foreground (`bash run_batch.sh ...`), never by inlining an equivalent
# multi-line while-loop as a single string passed through a backgrounded
# shell/eval call. That pattern was observed to hang silently - the outer
# shell process stays alive with no child doing real work, and nothing
# ever gets written to the results file, with no error surfaced. A
# foreground call to this actual file gives an immediate, unambiguous
# pass/fail instead of a silent hang you have to separately detect.
#
# ALSO IMPORTANT: pass a pre-generated deps dump (see dump_ninja_deps.py,
# generate it ONCE before the first batch). find_fallback_tu.py's module
# docstring has the full rationale.
set -u

REPO="$1"
BUILD_DIR="$2"
BATCH_FILE="$3"
RESULTS="$4"
LEVEL="${5:-remove}"
DEPS_DUMP="${6:-}"
MEASURE_CLOSURE="${7:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Backstop for a hang anywhere outside the IWYU call itself. Must stay strictly above
# process_header.py's --iwyu-timeout (120s), which reports an IWYU overrun with a
# proper JSON line; killing the process from out here instead yields only a bare
# "timeout" with no mode or detail.
IWYU_TIMEOUT=120
HARD_TIMEOUT=150
VALIDATE_ROUNDS=3
MEASURE_TIMEOUT=120

EXTRA_ARGS=()
if [ "$LEVEL" = "targeted" ]; then
  # targeted recompiles the TU once per validation round on top of the initial
  # IWYU run, so the backstop has to cover all of them. It must never fire first:
  # process_header.py restores the pre-run content on SIGTERM, but only its own
  # give-up path reports WHY a header was left alone.
  HARD_TIMEOUT=$(( IWYU_TIMEOUT * (VALIDATE_ROUNDS + 1) + 60 ))
  EXTRA_ARGS=(--validate-rounds "$VALIDATE_ROUNDS" --validate-timeout "$IWYU_TIMEOUT")
fi

# Two preprocess-only runs per changed header, on top of everything above. Folded
# into the backstop rather than left to chance: the measurement is diagnostic, so
# having it push a header into an outside kill (losing the result line that
# describes real edits already on disk) would be the worst possible trade.
case "$MEASURE_CLOSURE" in
  1|yes|true)
    EXTRA_ARGS+=(--measure-closure --measure-timeout "$MEASURE_TIMEOUT")
    HARD_TIMEOUT=$(( HARD_TIMEOUT + 2 * MEASURE_TIMEOUT ))
    ;;
esac

touch "$RESULTS"

DEPS_ARGS=()
if [ -n "$DEPS_DUMP" ]; then
  DEPS_ARGS=(--deps-dump "$DEPS_DUMP")
fi

while IFS= read -r header; do
  [ -z "$header" ] && continue
  timeout "$HARD_TIMEOUT" python3 "$SCRIPT_DIR/process_header.py" "$header" --repo "$REPO" \
    --build-dir "$BUILD_DIR" --level "$LEVEL" --iwyu-timeout "$IWYU_TIMEOUT" \
    "${EXTRA_ARGS[@]}" "${DEPS_ARGS[@]}" >> "$RESULTS" 2>> "$RESULTS.errors.log"
  rc=$?
  if [ "$rc" -eq 124 ]; then
    echo "{\"header\": \"$header\", \"status\": \"skipped\", \"detail\": \"hard timeout (${HARD_TIMEOUT}s), killed outside iwyu\"}" >> "$RESULTS"
  fi
done < "$BATCH_FILE"

echo "batch complete: $BATCH_FILE ($(wc -l < "$RESULTS") total result lines so far)"
