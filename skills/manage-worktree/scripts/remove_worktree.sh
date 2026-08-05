#!/usr/bin/env bash
# Usage: remove_worktree.sh <worktree_path> [--force]
#   worktree_path — absolute path to the worktree to remove
#   --force       — skip unsaved-work check and force removal
set -euo pipefail

WORKTREE_PATH="$1"
FORCE="${2:-}"

if [ ! -d "$WORKTREE_PATH" ]; then
    echo "Error: worktree path does not exist: $WORKTREE_PATH" >&2
    exit 1
fi

if [ "$FORCE" != "--force" ]; then
    uncommitted="$(git -C "$WORKTREE_PATH" status --short)"
    unpushed="$(git -C "$WORKTREE_PATH" log --oneline "origin/$(git -C "$WORKTREE_PATH" rev-parse --abbrev-ref HEAD)..HEAD" 2>/dev/null || true)"

    if [ -n "$uncommitted" ] || [ -n "$unpushed" ]; then
        echo "Unsaved work detected in $WORKTREE_PATH:" >&2
        [ -n "$uncommitted" ] && echo "  Uncommitted changes:" >&2 && echo "$uncommitted" | sed 's/^/    /' >&2
        [ -n "$unpushed"    ] && echo "  Unpushed commits:"   >&2 && echo "$unpushed"    | sed 's/^/    /' >&2
        echo "" >&2
        echo "Re-run with --force to discard and remove." >&2
        exit 1
    fi
fi

git worktree remove ${FORCE:+--force} "$WORKTREE_PATH"
echo "Worktree $(basename "$WORKTREE_PATH") removed."
