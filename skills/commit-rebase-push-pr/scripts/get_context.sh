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

echo "REMOTE_MAIN_BRANCH=$REMOTE_MAIN_BRANCH"
echo "SOURCE_BRANCH=$SOURCE_BRANCH"
echo "TARGET_BRANCH=$TARGET_BRANCH"
echo "COMMIT_NEEDED=$COMMIT_NEEDED"
echo "PLATFORM=$PLATFORM"
echo "GIT_REPO_BASE=$GIT_REPO_BASE"
echo "PROJECT_PATH=$PROJECT_PATH"
