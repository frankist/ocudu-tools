#!/usr/bin/env bash
# get_context.sh <issue_url>
# Checks glab is installed and authenticated, parses the issue URL, fetches issue data.
# Outputs: gitlab host, project path, issue iid, then the full issue JSON.
set -euo pipefail

URL="${1:-}"
if [[ -z "$URL" ]]; then
  echo "Error: GitLab issue URL required as argument" >&2
  exit 1
fi

if ! command -v glab >/dev/null 2>&1; then
  echo "Error: glab is not installed. See https://gitlab.com/gitlab-org/cli#installation" >&2
  exit 1
fi

# Parse https://<host>/<project_path>/-/issues/<iid>
GITLAB_HOST=$(echo "$URL" | sed 's|https://||' | cut -d/ -f1)
PROJECT_PATH=$(echo "$URL" | sed "s|https://$GITLAB_HOST/||" | sed 's|/-/.*||')
ISSUE_IID=$(echo "$URL" | grep -oE '[0-9]+$')

if [[ -z "$GITLAB_HOST" || -z "$PROJECT_PATH" || -z "$ISSUE_IID" ]]; then
  echo "Error: could not parse GitLab issue URL: $URL" >&2
  exit 1
fi

if ! glab auth status --hostname "$GITLAB_HOST" >/dev/null 2>&1; then
  echo "Error: not authenticated with $GITLAB_HOST. Run: glab auth login --hostname $GITLAB_HOST" >&2
  exit 1
fi

echo "gitlab host:  $GITLAB_HOST"
echo "project path: $PROJECT_PATH"
echo "issue iid:    $ISSUE_IID"

ISSUE_JSON=$(glab issue view "$ISSUE_IID" \
  --repo "$GITLAB_HOST/$PROJECT_PATH" \
  --comments \
  --output json)

echo "$ISSUE_JSON" | jq -r '
  "title:      " + .title,
  "labels:     " + ([.labels[]] | join(", ")),
  "milestone:  " + (.milestone.title // "(none)"),
  "assignees:  " + ([.assignees[].username] | join(", ")),
  "\ndescription:",
  .description,
  "\ncomments (" + (.comments | length | tostring) + "):",
  (.comments[]? | "[\(.author.username)]: \(.body)")
'
