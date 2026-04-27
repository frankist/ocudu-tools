#!/usr/bin/env bash
# fetch_mr.sh <gitlab_base_url> <project_path> <mr_iid>
# Outputs: {"mr":{...},"pipelines":[...]} — MR metadata + last 5 pipelines (newest first)
set -euo pipefail

GITLAB_URL="$1"
PROJECT="$2"
MR_IID="$3"

if [[ -z "${GITLAB_AI_TOKEN:-}" ]]; then
  echo "Error: GITLAB_AI_TOKEN is not set" >&2
  exit 1
fi

ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe=''))" "$PROJECT")
BASE="$GITLAB_URL/api/v4/projects/$ENC"

MR=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" "$BASE/merge_requests/$MR_IID")
if [[ -z "$MR" ]]; then
  echo "Error: MR not found or API request failed" >&2
  exit 1
fi

PIPELINES=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" \
  "$BASE/merge_requests/$MR_IID/pipelines?per_page=5&order_by=id&sort=desc")

printf '{"mr":%s,"pipelines":%s}\n' "$MR" "$PIPELINES"
