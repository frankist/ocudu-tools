---
name: commit-rebase-push-pr
description: Stage tracked changes, handle untracked files, commit with a good message, rebase on a target branch, push to remote, and create a PR/MR.
version: 1.0.0
disable-model-invocation: true
user-invocable: true
allowed-tools: false
context: fork
---

# Commit, Rebase, Push, and Create PR/MR

Finalizes your work by staging changes, creating a well-crafted commit, rebasing on a target branch (default: remote main), pushing to remote, and creating a PR/MR. It ensures you don't commit directly on the target branch.

## Input

Optional arguments:

- `--title <title>` — PR/MR title (default: auto-derived from branch name or commit message)
- `--target <branch>` — target branch for rebase and PR/MR (default: remote main branch)
- `-y` — automatically answer yes to rebase, push, and PR/MR creation confirmations

Examples:
- `/commit-rebase-push-pr` — stage changes, commit with prompted message, rebase on main, and optionally push/create PR
- `/commit-rebase-push-pr -y` — same as above but automatically proceed without prompts
- `/commit-rebase-push-pr --title "Fix login validation"` — supply custom PR/MR title (commit message is prompted separately)
- `/commit-rebase-push-pr --target develop` — rebase on and target the develop branch instead of main
- `/commit-rebase-push-pr --title "Fix login validation" --target develop -y` — custom PR/MR title, custom target, automatic mode

## Phase 1 - Resolve branches.

To determine the name of the remote origin main branch, run:
```bash
git ls-remote --symref origin HEAD | awk '/^ref:/ { sub("refs/heads/", "", $2); print $2 }'
```
and save it to the variable `REMOTE_MAIN_BRANCH`.

To determine the source branch, run:
```bash
git branch --show-current
```
and save it in `SOURCE_BRANCH`.

Determine the target branch:
- If `--target` argument is supplied, use it as `TARGET_BRANCH`
- Otherwise, set `TARGET_BRANCH=$REMOTE_MAIN_BRANCH`

If `$SOURCE_BRANCH == $TARGET_BRANCH`, write to the console "You are currently on the target branch ('$TARGET_BRANCH'). To commit changes, you should work on a separate branch. What do you want to do?" and present the options:
- **1. Stop**: exit the skill gracefully with a message.
- **2. Create and checkout a new branch**: where the user can write the branch name. Validate it (no spaces, valid git branch name, different than `$TARGET_BRANCH`). Run `git checkout -b <name>` and continue to the next step.
- **3. Work on `$TARGET_BRANCH`**: keep working on the target branch.

## Phase 2 - Add local changes to staged

Check for pending changes first:
```bash
git status --porcelain
```

If there are no modified tracked files and no untracked files, skip to Phase 4. (The user may have already committed changes, and we can proceed with rebase/push/PR.)

If there are untracked files:
- Count them and display the list (capped to the first few lines)
- Ask: "Found N untracked files. What should I do?" with options:
  - **Abort**: stop the skill
  - **Add all**: `git add <all untracked files>`
  - **Delete all**: `rm -rf` on all untracked files (confirm with user first)
  - **Exclude all**: `echo '<file>' >> .git/info/exclude` for each untracked file

For modified tracked files, run:
```bash
git add -u
```
to stage all tracked modifications.

## Phase 3. Commit with a good message

If there are no staged changes, skip this phase and proceed to Phase 4.

If there are staged changes:
1. Display what's being committed via `git diff --staged --name-status`
2. Prompt the user for a commit message:
   - **Subject line** (required): first line of commit message in imperative mood (~50 chars)
   - **Body** (optional): additional context explaining the why. User enters blank line to finish.
3. Commit with the provided message, without Co-Authored-By trailers
4. Example subject: `Fix login flow validation bug`

## Phase 4. Rebase on target branch.

If `-y` flag is not set, ask the user: "Do you want to rebase your branch on `origin/$TARGET_BRANCH`?" with options:
- **Yes**: Proceed with rebase
- **No**: Stop the skill gracefully

If the user chooses Yes or `-y` flag is set:
```bash
git fetch origin
git rebase origin/${TARGET_BRANCH}
```

If there are conflicts, run `git rebase --abort`, tell the user: "Rebase conflicts detected in: <list of conflicted files>. Please resolve them manually and re-run the skill." and stop skill.

## Phase 5. Push to remote.

If `-y` flag is not set, ask the user: "Do you want to push `$SOURCE_BRANCH` to remote?" with options:
- **Yes**: run `git push origin --force-with-lease $SOURCE_BRANCH`
- **No**: Stop the skill gracefully and let the user know the branch is ready to push whenever they want.

If the user chooses Yes or `-y` flag is set, do the following steps:
- check if `$REMOTE_MAIN_BRANCH == $SOURCE_BRANCH`. If so, print an error telling the user that it is forbidden to push to remote main branch and stop the skill.
- run:
```bash
git push origin --force-with-lease $SOURCE_BRANCH
```

## Phase 6. Detect platform and extract repository info

If `-y` flag is not set, ask the user: "Do you want to create a PR/MR for your branch with target `origin/$TARGET_BRANCH`?" with options:
- **Yes**: Proceed with PR/MR
- **No**: Stop the skill gracefully

If the user chooses Yes or `-y` flag is set, determine the platform and extract necessary variables:

```bash
GIT_REMOTE=$(git config --get remote.origin.url)
```

Detect platform:
- **GitHub**: if `$GIT_REMOTE` contains `github.com`, set `PLATFORM=github`
- **GitLab**: if `$GIT_REMOTE` contains `gitlab.com` or other GitLab hosts, set `PLATFORM=gitlab`

Extract repository information:
- **GitHub**: Extract `PROJECT_PATH` from the remote URL (e.g., `owner/repo` from `https://github.com/owner/repo.git`)
- **GitLab**: Extract `GIT_REPO_BASE` (the host base, e.g., `https://gitlab.com`) and `PROJECT_PATH` (the full path including groups, e.g., `group/subgroup/project`)

## Phase 7. Draft PR/MR Title and Description

To compare the local branch `SOURCE_BRANCH` with the target branch, run:
```bash
git log "origin/${TARGET_BRANCH}...HEAD" --oneline 2>/dev/null | head -20
```

If there are no commits ahead (empty output), stop the skill gracefully and tell the user: "No commits found between `$SOURCE_BRANCH` and `origin/$TARGET_BRANCH`. Nothing to create a PR/MR for."

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

## Phase 8. Confirm with the User

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

Where `<review_url>` is determined by `$PLATFORM`:
- GitHub: `https://github.com/<PROJECT_PATH>/compare/<TARGET_BRANCH>...<SOURCE_BRANCH>`
- GitLab: `<GIT_REPO_BASE>/<PROJECT_PATH>/-/merge_requests/new`

- **yes** — continue to next phase.
- **edit title** — ask for a new title, then re-show the draft.
- **edit description** — ask for replacement description text, then re-show the draft.
- **cancel** — stop with "PR/MR creation cancelled."

## Phase 9. Create PR/MR

Based on `$PLATFORM`, execute the appropriate command:

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
If `create_mr.sh` exits non-zero, print its stderr output and stop.

The script assigns the PR/MR to the git user matching `git config user.email`.

On success the script outputs the MR web URL. Display:
```
MR/PR created: <web_url>
```

On failure (non-zero exit or empty output), print the raw error and stop.



