#!/usr/bin/env bash
# create_mr.sh <gitlab_base_url> <project_path> <source_branch> <target_branch> <title> <description>
# Requires GITLAB_AI_TOKEN env var. Outputs: MR web URL.
set -euo pipefail

GITLAB_URL="$1"
PROJECT="$2"
SRC="$3"
TGT="$4"
TITLE="$5"
DESC="$6"

if [[ -z "${GITLAB_AI_TOKEN:-}" ]]; then
  echo "Error: GITLAB_AI_TOKEN is not set" >&2
  exit 1
fi

ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe=''))" "$PROJECT")

EMAIL=$(git config user.email)
ASSIGNEE_ID=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" "$GITLAB_URL/api/v4/users?search=$EMAIL" | jq '.[0].id')

PAYLOAD=$(jq -n \
  --arg src "$SRC" \
  --arg tgt "$TGT" \
  --arg title "$TITLE" \
  --arg desc "$DESC" \
  --argjson assignee "$ASSIGNEE_ID" \
  '{source_branch:$src,target_branch:$tgt,title:$title,description:$desc,remove_source_branch:true,assignee_id:$assignee}')

RESULT=$(curl -sf -X POST \
  -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$GITLAB_URL/api/v4/projects/$ENC/merge_requests")

echo "$RESULT" | jq -r '.web_url'
