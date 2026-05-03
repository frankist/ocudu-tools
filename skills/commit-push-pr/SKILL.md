---
name: commit-push-pr
description: Stage tracked changes, handle untracked files, commit with a good message, rebase on main, and create a PR/MR
version: 1.1.0
disable-model-invocation: true
user-invocable: true
allowed-tools: false
context: fork
---

# Commit, Push, and Create PR

Finalizes your work by staging changes, creating a well-crafted commit, rebasing on the main branch, and opening a PR/MR for review instead of pushing directly to main. Works with both GitHub and GitLab repositories.

## Input

Optional arguments after the skill name:

- `[target_branch]` — the branch to merge into (default: auto-detected from repo)
- `[title]` — MR title (default: auto-derived from branch name and recent commits)

Examples:
- `/commit-push-pr` — auto-detect everything
- `/commit-push-pr dev` — specify target branch
- `/commit-push-pr dev "fix: my title"` — specify both

**Find `SKILL_DIR`** (directory containing this SKILL.md) for absolute script paths.

## Workflow

### 1. Detect Context for PR/MR

Run the detection script and eval its output to set context variables:
```bash
eval "$(bash "$SKILL_DIR/scripts/detect_context.sh" "${TARGET_BRANCH_ARG:-}")"
```

This sets: `GIT_PROVIDER`, `GIT_REPO_HOST`, `GIT_REPO_BASE`, `PROJECT_PATH`, `SOURCE_BRANCH`, `TARGET_BRANCH`.

The script handles all failure cases and exits non-zero with a human-readable error. If it fails, stop and show the error to the user — do not proceed to the next step.

**Check if source and target are the same:**

If `$SOURCE_BRANCH == $TARGET_BRANCH`, present two options:

```
You are currently on the target branch ('$SOURCE_BRANCH'). 
To create a PR/MR, you need to work on a separate branch.

What would you like to do?
  a) Stop — I'll create a branch myself and re-run the skill
  b) Create a new branch — provide a name and I'll create & checkout it
```

- **a) Stop**: exit the skill gracefully with a message.
- **b) Create a new branch**: ask the user for a branch name. Validate it (no spaces, valid git branch name). Run `git checkout -b <name>` and continue to step 2.

### 2. Stage Tracked Changes

Check for pending changes first:
```bash
git status --porcelain
```
If there are no modified tracked files and no untracked files, skip steps 2 and 3 entirely.

Otherwise, run `git add` on all modified tracked files:
- Stage selectively or use `git add -u` to stage all tracked modifications at once

### 3. Handle Untracked Files

Skip this step if `git status --porcelain` reported no untracked files (`??` lines).

Otherwise, for each untracked file or directory, ask the user:

```
What should I do with [filename]?
  a) Add it to the repository
  b) Delete it
  c) Add it to .git/info/exclude (ignore permanently)
```

Then take the corresponding action:
- **Add**: `git add <file>`
- **Delete**: `rm -rf <file>` (confirm with user first)
- **Exclude**: `echo '<file>' >> .git/info/exclude`

### 4. Commit with a Good Message

Once staging is complete:
1. Read git status and git diff to understand what's being committed
2. Draft a concise commit message (imperative mood, ~50 chars subject line)
3. If there are multiple changes, include a detailed body explaining the why
4. Commit without Co-Authored-By trailers
5. Example: `git commit -m "Fix login flow validation bug"`

### 5. Rebase on Target Branch

Ensure your branch is up-to-date with the target branch:
```bash
git fetch origin
git rebase origin/${TARGET_BRANCH}
```

If there are conflicts, ask the user:

```
Rebase conflicts detected in: <list of conflicted files>

How would you like to proceed?
  a) Abort — I'll resolve the conflicts manually and re-run the skill
  b) Automatically resolve conflicts using the agent
```

- **a) Abort**: run `git rebase --abort` and stop. Tell the user to resolve conflicts, then re-run the skill.
- **b) Automatically resolve**: read each conflicted file, reason about the correct merge, edit the file to resolve the conflict markers, then `git add <file>` and continue with `git rebase --continue`. Repeat until the rebase completes. If a conflict is too ambiguous to resolve safely, abort and tell the user which file needs manual attention.

### 6. Gather Context for PR/MR Message

**Recent commits on this branch (relative to target):**
```bash
git log "origin/${TARGET_BRANCH}...HEAD" --oneline 2>/dev/null | head -20
```
If this fails (e.g. target branch not fetched locally), fall back to:
```bash
git log HEAD~10...HEAD --oneline
```

### 7. Draft PR/MR Title and Description

**Title** (in order of precedence):
1. User-supplied argument.
2. If there is exactly one commit ahead, use that commit's subject line.
3. Otherwise, prettify the branch name: replace `-` and `_` with spaces, capitalize the first word.

**Description:** A plain bullet list of commit subjects from step 6 (gathered context), oldest first:
```
- <oldest commit subject>
- ...
- <newest commit subject>
```

If there is only one commit and it has a body, use the body as the description instead of a bullet list.

### 8. Confirm with User

Present the draft before creating anything:

```
About to create PR/MR:

  Title:  <title>
  Source: <source_branch> → <target_branch>
  URL:    <review_url>

  Description:
  ---
  <description>
  ---

Proceed? (yes / edit title / edit description / cancel)
```

Where `<review_url>` is:
- GitHub: `https://github.com/<PROJECT_PATH>/compare/<target_branch>...<source_branch>`
- GitLab: `<GIT_REPO_BASE>/<PROJECT_PATH>/-/merge_requests/new`

- **yes** — continue to step 9.
- **edit title** — ask for a new title, then re-show the draft.
- **edit description** — ask for replacement description text, then re-show the draft.
- **cancel** — stop with "PR/MR creation cancelled."

### 9. Push Branch and Create PR/MR

Push the branch to origin first:
```bash
git push origin "$SOURCE_BRANCH"
```

**Do NOT** `git push origin $TARGET_BRANCH` — always create a PR/MR for review first.

#### GitHub
```bash
gh pr create \
  --title "$TITLE" \
  --base "$TARGET_BRANCH" \
  --body "$DESCRIPTION"
```

#### GitLab
```bash
bash "$SKILL_DIR/scripts/create_mr.sh" \
  "$GIT_REPO_BASE" "$PROJECT_PATH" \
  "$SOURCE_BRANCH" "$TARGET_BRANCH" \
  "$TITLE" "$DESCRIPTION"
```

The script assigns the MR to the git user matching `git config user.email`.

On success the script outputs the MR web URL. Display:
```
MR/PR created: <web_url>
```

On failure (non-zero exit or empty output), print the raw error and stop.

## Error Handling

All step-1 failure cases (detached HEAD, unparseable remote, unsupported host, failed auth, private project without token, same source/target branch, API errors) are caught by `detect_context.sh`, which prints a human-readable message to stderr and exits non-zero.

For step 9, if `create_mr.sh` exits non-zero, print its stderr output and stop.
