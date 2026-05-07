#!/usr/bin/env bash
# get_context.sh [target_branch]
# Fetches origin and prints KEY=VALUE context variables for the skill.
set -euo pipefail

git fetch origin

REMOTE_MAIN_BRANCH="$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@refs/remotes/origin/@@')"
SOURCE_BRANCH="$(git branch --show-current)"
TARGET_BRANCH="${1:-$REMOTE_MAIN_BRANCH}"
PENDING_STATUS="$(git status --porcelain)"
GIT_REMOTE=$(git config --get remote.origin.url)
PLATFORM=$(echo "$GIT_REMOTE" | grep -oE 'github|gitlab' | head -1)
PROJECT_PATH=$(echo "$GIT_REMOTE" | sed -E 's|^https?://[^/]+/||; s|^git@[^:]+:||; s|\.git$||')
ERROR_MESSAGE=""

if echo "$GIT_REMOTE" | grep -q 'github'; then
  GIT_REPO_BASE="https://github.com"
else
  GIT_REPO_BASE=$(echo "$GIT_REMOTE" | sed -E 's|(https?://[^/]+)/.*|\1|; s|git@([^:]+):.*|https://\1|')
fi

RED=$'\e[31m'; RESET=$'\e[0m'

if [ "$SOURCE_BRANCH" = "$TARGET_BRANCH" ]; then
  echo "${RED}ERROR: You are on the target branch ('$TARGET_BRANCH'). Switch to a feature branch before running this skill.${RESET}"
  exit 1
fi

if [ "$SOURCE_BRANCH" = "$REMOTE_MAIN_BRANCH" ]; then
  echo "${RED}ERROR: You are on the remote main branch ('$REMOTE_MAIN_BRANCH'). Switch to a feature branch before running this skill.${RESET}"
  exit 1
fi

UNTRACKED="$(echo "$PENDING_STATUS" | grep '^??' || true)"
UNSTAGED="$(echo "$PENDING_STATUS" | grep '^.[^ ]' || true)"
if [ -n "$UNTRACKED" ] || [ -n "$UNSTAGED" ]; then
  echo "${RED}ERROR: There are untracked or unstaged changes. Stage or discard them before running this skill.${RESET}"
  exit 1
fi

STAGED="$(echo "$PENDING_STATUS" | grep '^[^ ?]' || true)"
COMMIT_NEEDED=false
[ -n "$STAGED" ] && COMMIT_NEEDED=true
USER_EMAIL=$(git config user.email)

EXISTING_PR_TITLE=""
EXISTING_PR_URL=""
if [ "$PLATFORM" = "github" ]; then
  EXISTING_PR_JSON=$(gh pr list --head "$SOURCE_BRANCH" --base "$TARGET_BRANCH" --json title,url --limit 1 2>/dev/null || echo "[]")
  EXISTING_PR_TITLE=$(echo "$EXISTING_PR_JSON" | python3 -c "import json,sys; items=json.load(sys.stdin); print(items[0]['title'] if items else '')")
  EXISTING_PR_URL=$(echo "$EXISTING_PR_JSON" | python3 -c "import json,sys; items=json.load(sys.stdin); print(items[0]['url'] if items else '')")
elif [ "$PLATFORM" = "gitlab" ]; then
  ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe=''))" "$PROJECT_PATH")
  EXISTING_PR_JSON=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" \
    "$GIT_REPO_BASE/api/v4/projects/$ENC/merge_requests?source_branch=$SOURCE_BRANCH&target_branch=$TARGET_BRANCH&state=opened" 2>/dev/null || echo "[]")
  EXISTING_PR_TITLE=$(echo "$EXISTING_PR_JSON" | python3 -c "import json,sys; items=json.load(sys.stdin); print(items[0]['title'] if items else '')")
  EXISTING_PR_URL=$(echo "$EXISTING_PR_JSON" | python3 -c "import json,sys; items=json.load(sys.stdin); print(items[0]['web_url'] if items else '')")
fi

echo "REMOTE_MAIN_BRANCH=$REMOTE_MAIN_BRANCH"
echo "SOURCE_BRANCH=$SOURCE_BRANCH"
echo "TARGET_BRANCH=$TARGET_BRANCH"
echo "COMMIT_NEEDED=$COMMIT_NEEDED"
echo "PLATFORM=$PLATFORM"
echo "GIT_REPO_BASE=$GIT_REPO_BASE"
echo "PROJECT_PATH=$PROJECT_PATH"
echo "USER_EMAIL=$USER_EMAIL"
echo "EXISTING_PR_TITLE=$EXISTING_PR_TITLE"
echo "EXISTING_PR_URL=$EXISTING_PR_URL"
