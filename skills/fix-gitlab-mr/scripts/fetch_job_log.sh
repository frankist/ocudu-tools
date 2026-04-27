#!/usr/bin/env bash
# fetch_job_log.sh <gitlab_base_url> <project_path> <job_id> <output_file>
# Downloads the raw job trace to <output_file>.
# Strips ANSI escape sequences for easier grepping.
set -euo pipefail

GITLAB_URL="$1"
PROJECT="$2"
JOB_ID="$3"
OUTPUT="$4"

if [[ -z "${GITLAB_AI_TOKEN:-}" ]]; then
  echo "Error: GITLAB_AI_TOKEN is not set" >&2
  exit 1
fi

ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe=''))" "$PROJECT")

curl -sf -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" \
  "$GITLAB_URL/api/v4/projects/$ENC/jobs/$JOB_ID/trace" \
  | sed 's/\x1b\[[0-9;]*[mGKHF]//g' \
  > "$OUTPUT"

echo "Log saved to $OUTPUT ($(wc -l < "$OUTPUT") lines, $(du -sh "$OUTPUT" | cut -f1))"
