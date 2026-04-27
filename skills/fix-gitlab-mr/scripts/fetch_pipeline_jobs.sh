#!/usr/bin/env bash
# fetch_pipeline_jobs.sh <gitlab_base_url> <project_path> <pipeline_id>
# Outputs: JSON array of all jobs for the pipeline.
set -euo pipefail

GITLAB_URL="$1"
PROJECT="$2"
PIPELINE_ID="$3"

if [[ -z "${GITLAB_AI_TOKEN:-}" ]]; then
  echo "Error: GITLAB_AI_TOKEN is not set" >&2
  exit 1
fi

ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe=''))" "$PROJECT")
BASE="$GITLAB_URL/api/v4/projects/$ENC"

# Two pages covers up to 200 jobs — more than enough for any real pipeline
P1=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" \
  "$BASE/pipelines/$PIPELINE_ID/jobs?per_page=100&page=1")
P2=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" \
  "$BASE/pipelines/$PIPELINE_ID/jobs?per_page=100&page=2")

python3 -c "
import json, sys
p1 = json.loads(sys.argv[1])
p2 = json.loads(sys.argv[2])
combined = p1 + p2
print(json.dumps(combined))
" "$P1" "$P2"
