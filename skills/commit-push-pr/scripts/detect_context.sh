#!/usr/bin/env bash
# detect_context.sh [target_branch]
# Detects git provider, project path, and source/target branch.
# Prints KEY=VALUE lines suitable for eval. Exits non-zero on error.
set -euo pipefail

TARGET_BRANCH_ARG="${1:-}"

# Current branch
SOURCE_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$SOURCE_BRANCH" == "HEAD" ]]; then
  echo "Error: Cannot create PR/MR from a detached HEAD." >&2
  exit 1
fi

# Parse remote URL
REMOTE_URL=$(git remote get-url origin 2>/dev/null) || {
  echo "Error: No 'origin' remote found." >&2
  exit 1
}

if [[ "$REMOTE_URL" =~ ^git@([^:]+):(.+)$ ]]; then
  GIT_REPO_HOST="${BASH_REMATCH[1]}"
  PROJECT_PATH="${BASH_REMATCH[2]%.git}"
elif [[ "$REMOTE_URL" =~ ^https?://([^/]+)/(.+)$ ]]; then
  GIT_REPO_HOST="${BASH_REMATCH[1]}"
  PROJECT_PATH="${BASH_REMATCH[2]%.git}"
else
  echo "Error: Cannot parse remote URL '$REMOTE_URL'. Fix with: git remote set-url origin <url>" >&2
  exit 1
fi

if [[ "$GIT_REPO_HOST" == *"github"* ]]; then
  GIT_PROVIDER="github"
elif [[ "$GIT_REPO_HOST" == *"gitlab"* ]]; then
  GIT_PROVIDER="gitlab"
else
  echo "Error: Unsupported git host '$GIT_REPO_HOST'. Only GitHub and GitLab are supported." >&2
  exit 1
fi

GIT_REPO_BASE="https://$GIT_REPO_HOST"

# Check authentication
if [[ "$GIT_PROVIDER" == "github" ]]; then
  gh auth status &>/dev/null || {
    echo "Error: gh is not authenticated. Run: gh auth login" >&2
    exit 1
  }
fi

# Detect target branch
if [[ -n "$TARGET_BRANCH_ARG" ]]; then
  TARGET_BRANCH="$TARGET_BRANCH_ARG"
elif [[ "$GIT_PROVIDER" == "github" ]]; then
  TARGET_BRANCH=$(gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name')
elif [[ "$GIT_PROVIDER" == "gitlab" ]]; then
  ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe=''))" "$PROJECT_PATH")
  HTTP_CODE=$(curl -s -o /tmp/gl_project_$$.json -w "%{http_code}" "$GIT_REPO_BASE/api/v4/projects/$ENC")
  if [[ "$HTTP_CODE" == "200" ]]; then
    TARGET_BRANCH=$(jq -r '.default_branch' /tmp/gl_project_$$.json)
  elif [[ "$HTTP_CODE" == "401" || "$HTTP_CODE" == "404" ]]; then
    if [[ -z "${GITLAB_AI_TOKEN:-}" ]]; then
      echo "Error: This appears to be a private GitLab project and GITLAB_AI_TOKEN is not set." >&2
      echo "Add it to ~/.zshrc or ~/.bashrc:" >&2
      echo "  export GITLAB_AI_TOKEN=<your-personal-access-token>" >&2
      echo "Create a token at $GIT_REPO_BASE/-/user_settings/personal_access_tokens with 'api' scope." >&2
      exit 1
    fi
    TARGET_BRANCH=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" \
      "$GIT_REPO_BASE/api/v4/projects/$ENC" | jq -r '.default_branch')
  else
    echo "Error: GitLab API returned HTTP $HTTP_CODE for project '$PROJECT_PATH'." >&2
    exit 1
  fi
  rm -f /tmp/gl_project_$$.json
fi

echo "GIT_PROVIDER=$GIT_PROVIDER"
echo "GIT_REPO_HOST=$GIT_REPO_HOST"
echo "GIT_REPO_BASE=$GIT_REPO_BASE"
echo "PROJECT_PATH=$PROJECT_PATH"
echo "SOURCE_BRANCH=$SOURCE_BRANCH"
echo "TARGET_BRANCH=$TARGET_BRANCH"
