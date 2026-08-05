---
name: manage-worktree
description: >
  Create or remove a git worktree for the current project with ccache sharing enabled across
  worktrees. Trigger phrases: "create worktree", "add worktree", "setup worktree", "new worktree
  for <branch>", "remove worktree", "delete worktree", "clean up worktree".
version: 1.0.0
user-invocable: true
---

# manage-worktree

Create or remove a git worktree with ccache sharing across worktrees. The build directory lives
inside the worktree; `CCACHE_BASEDIR` and `-fdebug-prefix-map` normalise paths so object files
cached in one worktree are reused in another. direnv (required) sets `CCACHE_BASEDIR` automatically
on `cd` via a generated `.envrc`.

## Trigger detection

- If the user says "remove", "delete", or "clean up" a worktree → jump to **[Remove](#remove)**.
- Otherwise → proceed with **[Create](#create)**.

## Create

### Phase 1 — Gather inputs

**Determine repo layout:**
```bash
git rev-parse --show-toplevel
```
Extract:
- `REPO_ROOT` — absolute path of the main repo
- `REPO_NAME` — `basename "$REPO_ROOT"`
- `REPO_PARENT` — `dirname "$REPO_ROOT"`
- `WORKTREES_DIR` — `"$REPO_PARENT/$REPO_NAME-worktrees"`

**Ask the user for two things** (can be combined in one message):
1. **Branch name** — the branch to check out in the new worktree. Suggest the current branch if it
   is not `main`/`master`/`dev`.
2. **Build type** — `Debug`, `RelWithDebInfo`, or `Release`.

### Phase 2 — Run the setup script

Run the script directly:

```bash
"${CLAUDE_SKILL_DIR}/scripts/create_worktree.sh" "$REPO_ROOT" "$BRANCH" "$BUILD_TYPE"
```

The script handles all remaining work: worktree creation (with local/remote/new-branch detection),
cmake configuration, `worktree.cmake` toolchain file, `.envrc` generation, and `direnv allow`. It
exits immediately with an error if direnv is not installed. It prints the final summary itself —
relay it to the user.

---

## Remove

### Phase 1 — Identify the worktree

```bash
git worktree list
```

Match the user's branch or path against the list. If ambiguous or unspecified, show the list
(excluding the main worktree) and ask the user to pick one.

### Phase 2 — Run the remove script

```bash
"${CLAUDE_SKILL_DIR}/scripts/remove_worktree.sh" "$WORKTREE_PATH"
```

If the script exits non-zero (unsaved work detected), show the output to the user and ask for
explicit confirmation. On confirmation, re-run with `--force`:

```bash
"${CLAUDE_SKILL_DIR}/scripts/remove_worktree.sh" "$WORKTREE_PATH" --force
```

---

## Error handling

| Situation | Action |
|---|---|
| `create_worktree.sh` exits non-zero | Read the error; if cmake failure, leave worktree intact and ask how to proceed |
| `remove_worktree.sh` exits non-zero | Unsaved work — show details, ask for confirmation, re-run with `--force` |
| Branch already checked out in another worktree | Tell the user which worktree has it; offer to reuse or pick a different branch |
| direnv not installed | `create_worktree.sh` exits with an error and prints install instructions |
| ccache not installed | No action needed — builds work, just without cross-worktree cache sharing |
