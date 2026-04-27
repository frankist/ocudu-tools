#!/usr/bin/env bash
# fetch_issue.sh <gitlab_base_url> <project_path> <issue_iid>
# Requires GITLAB_TOKEN env var. Outputs: {"issue":{...},"notes":[...]}
set -euo pipefail

GITLAB_URL="$1"
PROJECT="$2"
IID="$3"

if [[ -z "${GITLAB_AI_TOKEN:-}" ]]; then
  echo "Error: GITLAB_AI_TOKEN is not set" >&2
  exit 1
fi

ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe=''))" "$PROJECT")
BASE="$GITLAB_URL/api/v4/projects/$ENC"

ISSUE=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" "$BASE/issues/$IID")
if [[ -z "$ISSUE" ]]; then
  echo "Error: issue not found or API request failed" >&2
  exit 1
fi

NOTES=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" \
  "$BASE/issues/$IID/notes?per_page=100&sort=asc&order_by=created_at")

printf '{"issue":%s,"notes":%s}\n' "$ISSUE" "$NOTES"
