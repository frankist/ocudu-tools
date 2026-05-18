#!/usr/bin/env bash
# create_mr.sh <worktree_path> <source_branch> <target_branch> <title> <description>
# Outputs: MR web URL.
set -euo pipefail

WORKTREE_PATH="$1"
SRC="$2"
TGT="$3"
TITLE="$4"
DESC="$5"

cd "$WORKTREE_PATH"
glab mr create \
  --source-branch "$SRC" \
  --target-branch "$TGT" \
  --title "$TITLE" \
  --description "$DESC" \
  --assignee "@me" \
  --remove-source-branch \
  --yes
