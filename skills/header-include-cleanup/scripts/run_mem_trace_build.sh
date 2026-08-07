#!/usr/bin/env bash
# Clean rebuild of an OCUDU repo/worktree with clang, measuring peak RSS
# (via GNU `time -v`-style %M) for every C/C++ compile invocation, producing
# a memory-consumption report and metadata file under
# $BUILD_DIR/reports/clang-mem-trace-<timestamp>/.
#
# Run this directly in a real terminal (not backgrounded through an agent
# shell) since it takes a while.
#
# Usage: run_mem_trace_build.sh <path-to-ocudu-repo-or-worktree>
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <path-to-ocudu-repo-or-worktree>" >&2
  exit 1
fi

WORKTREE="$(cd "$1" && pwd)"
if [ ! -f "$WORKTREE/CMakeLists.txt" ] || [ ! -d "$WORKTREE/lib" ]; then
  echo "Error: $WORKTREE does not look like an OCUDU repo (no CMakeLists.txt / lib/)." >&2
  exit 1
fi

BUILD_DIR="$WORKTREE/build-mem-trace"
REPORTS_DIR="$BUILD_DIR/reports"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_DIR="$REPORTS_DIR/clang-mem-trace-$TIMESTAMP"
WRAPPER="$REPORTS_DIR/mem_wrapper.sh"
MEM_LOG="$REPORT_DIR/mem_raw.tsv"
REPORT_TXT="$REPORT_DIR/mem-report.txt"
REPORT_CSV="$REPORT_DIR/mem-report.csv"
META_FILE="$REPORT_DIR/mem-report-metadata.txt"

echo "== Cleaning build dir (preserving previous reports); creating report dir =="
if [ -d "$BUILD_DIR" ]; then
  find "$BUILD_DIR" -mindepth 1 -maxdepth 1 ! -name "$(basename "$REPORTS_DIR")" -exec rm -rf {} +
fi
mkdir -p "$REPORT_DIR"
: > "$MEM_LOG"

echo "== Generating compiler-launcher wrapper =="
cat > "$WRAPPER" <<'WRAPPER_EOF'
#!/usr/bin/env bash
# Compiler-launcher wrapper: runs the real compile invocation under GNU
# `/usr/bin/time` and appends "<maxrss_kb>\t<elapsed_s>\t<full argv>" to
# $OCUDU_MEM_LOG. Used as CMAKE_C_COMPILER_LAUNCHER / CMAKE_CXX_COMPILER_LAUNCHER.
: "${OCUDU_MEM_LOG:?OCUDU_MEM_LOG must be set}"

TMP="$(mktemp)"
/usr/bin/time -f "%M %e" -o "$TMP" -- "$@"
STATUS=$?
read -r MAXRSS_KB ELAPSED < "$TMP"
rm -f "$TMP"

{
  flock -x 9
  printf '%s\t%s\t%s\n' "$MAXRSS_KB" "$ELAPSED" "$*" >> "$OCUDU_MEM_LOG"
} 9>>"$OCUDU_MEM_LOG.lock"

exit "$STATUS"
WRAPPER_EOF
chmod +x "$WRAPPER"

echo "== Configuring cmake (clang, ccache disabled, memory-tracing launcher) =="
cmake -S "$WORKTREE" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_C_COMPILER=clang \
  -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_C_COMPILER_LAUNCHER="$WRAPPER" \
  -DCMAKE_CXX_COMPILER_LAUNCHER="$WRAPPER" \
  -G Ninja \
  -DLINKER=mold \
  -DBUILD_TESTING=On \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=On

echo "== Building (this can take a long while) =="
export OCUDU_MEM_LOG="$MEM_LOG"
BUILD_START_EPOCH=$(date +%s)
ninja -C "$BUILD_DIR" -j"$(nproc)" 2>&1 | tee "$BUILD_DIR/build.log"
BUILD_END_EPOCH=$(date +%s)
cp "$BUILD_DIR/build.log" "$REPORT_DIR/build.log"

echo "== Aggregating per-TU peak RSS =="
python3 - "$MEM_LOG" "$REPORT_TXT" "$REPORT_CSV" <<'PYEOF'
import re, sys, statistics

log_path, txt_path, csv_path = sys.argv[1:4]

SRC_RE = re.compile(r'\S+\.(?:cpp|cc|cxx|c)\b')

rows = []
with open(log_path) as f:
    for line in f:
        parts = line.rstrip("\n").split("\t", 2)
        if len(parts) != 3:
            continue
        maxrss_kb_s, elapsed_s, cmdline = parts
        try:
            maxrss_kb = int(maxrss_kb_s)
            elapsed = float(elapsed_s)
        except ValueError:
            continue
        m = SRC_RE.findall(cmdline)
        src = m[-1] if m else "<unknown>"
        rows.append((maxrss_kb / 1024.0, elapsed, src))

rows.sort(key=lambda r: r[0], reverse=True)

with open(csv_path, "w") as f:
    f.write("peak_rss_mb,elapsed_s,source_file\n")
    for rss, elapsed, src in rows:
        f.write(f"{rss:.1f},{elapsed:.2f},{src}\n")

n = len(rows)
with open(txt_path, "w") as f:
    if n == 0:
        f.write("No compile invocations captured.\n")
    else:
        rss_vals = [r[0] for r in rows]
        f.write(f"Translation units measured: {n}\n")
        f.write(f"Peak RSS  - max: {max(rss_vals):.1f} MB, "
                f"min: {min(rss_vals):.1f} MB, "
                f"mean: {statistics.mean(rss_vals):.1f} MB, "
                f"median: {statistics.median(rss_vals):.1f} MB\n")
        f.write(f"Sum of per-TU peak RSS: {sum(rss_vals):.1f} MB "
                "(not concurrent memory use - TUs build in parallel; "
                "see build's -j for actual overlap factor)\n\n")
        f.write("Top 30 memory-heavy translation units:\n")
        f.write(f"{'RSS (MB)':>10}  {'Time (s)':>8}  Source\n")
        for rss, elapsed, src in rows[:30]:
            f.write(f"{rss:10.1f}  {elapsed:8.2f}  {src}\n")

print(f"Parsed {n} compile invocations -> {txt_path}, {csv_path}")
PYEOF

echo "== Writing metadata =="
{
  echo "Build start (UTC):  $(date -u -d "@$BUILD_START_EPOCH" +"%Y-%m-%d %H:%M:%S")"
  echo "Build end (UTC):    $(date -u -d "@$BUILD_END_EPOCH" +"%Y-%m-%d %H:%M:%S")"
  echo "Build wall time:    $((BUILD_END_EPOCH - BUILD_START_EPOCH))s"
  echo "Worktree:           $WORKTREE"
  echo "Branch:             $(git -C "$WORKTREE" rev-parse --abbrev-ref HEAD)"
  echo "Commit:             $(git -C "$WORKTREE" rev-parse HEAD)"
  echo "Commit subject:     $(git -C "$WORKTREE" log -1 --pretty=%s)"
  echo "Compiler:           $(clang++ --version | head -1)"
  echo "Build type:         RelWithDebInfo"
  echo "Linker:             mold"
  echo "ccache:             disabled"
  echo "CMake generator:    Ninja"
  echo "nproc:              $(nproc)"
  echo "Memory measurement: per-TU peak RSS via GNU 'time -f \"%M %e\"' wrapped around each compile invocation"
  echo "Raw log:            $MEM_LOG"
  echo "Report txt:         $REPORT_TXT"
  echo "Report csv:         $REPORT_CSV"
  echo "Build log:          $REPORT_DIR/build.log"
} > "$META_FILE"

echo "Done."
echo "Report:   $REPORT_TXT"
echo "CSV:      $REPORT_CSV"
echo "Metadata: $META_FILE"
