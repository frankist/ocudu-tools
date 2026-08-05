#!/usr/bin/env bash
# get_context.sh [path-or-branch]
# Outputs current branch, remote main branch name, and resolved worktree path.
set -euo pipefail

WORKTREE_PATH=""
GIT=(git)

if [[ -n "${1:-}" ]]; then
  if [[ -d "$1" ]]; then
    # If arg is a directory, use it as worktree path.
    WORKTREE_PATH="$1"
  else
    # Treat as branch name — find its worktree path
    WORKTREE_PATH=$(git worktree list --porcelain \
      | awk -v branch="refs/heads/$1" '
          /^worktree / { path=$2 }
          $0 == "branch " branch { print path; exit }
        ')
    if [[ -z "$WORKTREE_PATH" ]]; then
      echo "Error: no worktree found for branch '$1'" >&2
      exit 1
    fi
  fi
  GIT=(git -C "$WORKTREE_PATH")
fi

CURRENT_BRANCH=$("${GIT[@]}" branch --show-current)
MAIN_BRANCH=$("${GIT[@]}" symbolic-ref refs/remotes/origin/HEAD | sed 's@refs/remotes/origin/@@')

if [[ "$CURRENT_BRANCH" == "$MAIN_BRANCH" ]]; then
  echo "Error: current branch is '$MAIN_BRANCH' — commits directly to main are not allowed." >&2
  exit 1
fi

# Stage tracked-file changes up front so the caller only has to decide on untracked files.
"${GIT[@]}" add -u
# Porcelain XY codes: X = index (staged) state, Y = worktree (unstaged) state, '??' = untracked.
# List every changed entry so staged-only files (e.g. "M ") are surfaced too, not just unstaged/untracked ones.
CHANGES=$("${GIT[@]}" status --porcelain || true)

echo "current branch: $CURRENT_BRANCH"
echo "main branch:    $MAIN_BRANCH"
[[ -n "$WORKTREE_PATH" ]] && echo "worktree path:  $WORKTREE_PATH"
[[ -n "$CHANGES" ]] && printf 'changes (porcelain XY; X=staged, Y=unstaged, ??=untracked):\n%s\n' "$CHANGES"
exit 0

