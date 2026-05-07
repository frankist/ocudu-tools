---
name: commit-rebase-push-pr
description: Stage tracked changes, handle untracked files, commit with a good message, rebase on a target branch, push to remote, and create a PR/MR.
version: 1.0.0
user-invocable: true
context: fork
agent: Explore
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/get_context.sh:*), Bash(git diff:*)
---

# Commit, Rebase, Push, and Create PR/MR

Finalizes your work by creating a well-crafted commit, rebasing on a target branch (default: remote main), pushing to remote, and creating a PR/MR, if it doesn't yet exist. It ensures you don't commit directly on the target branch, you don't create duplicate PRs/MRs for the same branch.

On completion, return a summary saying if the commit, rebase and PR were successful.

## Input

Optional arguments:

- `<target branch>` — target branch for rebase and PR/MR (default: remote main branch)

Examples:
- `/commit-rebase-push-pr` — stage changes, commit with prompted message, rebase on main, and optionally push/create PR
- `/commit-rebase-push-pr some_branch` — rebase on and target the some_branch branch instead of main

## Interaction and continuation rules

This skill may need missing information from the user.

When required information is missing:
1. Ask only for the missing information.
2. Before asking, state exactly what step will resume after the user replies.
3. Do not consider the task complete.
4. When the user replies with the requested information, continue from the next unfinished step of this skill.
5. Do not restart the workflow unless the user explicitly asks to restart.
6. Keep a brief checklist of completed and pending steps in your response so the next turn has enough context.

When asking the user to choose between options, prefer the native AskUserQuestion / interactive choice UI. If unavailable, present the same choices as a numbered list and ask the user to reply with the number or custom answer. Always continue the workflow after the user replies, unless they explicitly requested to stop the skill.

## Phase 1 - Repository context.

```!
${CLAUDE_SKILL_DIR}/scripts/get_context.sh "$ARGUMENTS"
```

Read the KEY=VALUE output and save: `REMOTE_MAIN_BRANCH`, `SOURCE_BRANCH`, `TARGET_BRANCH`, `COMMIT_NEEDED`, `PLATFORM`, `GIT_REPO_BASE`, `PROJECT_PATH`, `USER_EMAIL`, `EXISTING_PR_TITLE`, `EXISTING_PR_URL`.

If `COMMIT_NEEDED=false`, skip Phase 2, and tell the user: "No pending changes to commit".

If `EXISTING_PR_TITLE` is non-empty, skip Phases 5 and after and tell the user: "A PR/MR already exists for `$SOURCE_BRANCH`: <EXISTING_PR_TITLE> (<EXISTING_PR_URL>)".

## Phase 2. Commit with a good message

Based on the results of the `git diff`, generate a commit message with:
- **Subject line** (required): first line of commit message in imperative mood (~50 chars)
- **Body** (optional): additional context explaining the why. User enters blank line to finish.

Using the AskUserQuestion, ask the user if they agree or want to make changes. Do not add Co-Authored-By trailers. Once the commit is successful, move to Phase 3.

## Phase 3. Rebase on target branch.

```bash
git rebase origin/${TARGET_BRANCH}
```

If there are conflicts, run `git rebase --abort`, tell the user: "ERROR: Rebase conflicts detected in: <list of conflicted files>. Please resolve them manually and re-run the skill." and stop skill.

## Phase 4. Push to remote.

Run:
```bash
git push origin --force-with-lease $SOURCE_BRANCH
```

## Phase 5. Draft PR/MR Title and Description

To compare the local branch `SOURCE_BRANCH` with the target branch, run:
```bash
git log "origin/${TARGET_BRANCH}...HEAD" --oneline 2>/dev/null | head -20
```

If there are no commits ahead (empty output), stop the skill gracefully and tell the user: "No commits found between `$SOURCE_BRANCH` and `origin/$TARGET_BRANCH`. Nothing to create a PR/MR for."

**Title** (in order of precedence):
1. User-supplied argument.
2. If there is exactly one commit ahead, use that commit's subject line.
3. Otherwise, prettify the branch name: replace `-` and `_` with spaces, capitalize the first word.

**Description:** A plain bullet list of commit subjects from the git log output above, oldest first:
```
- <oldest commit subject>
- ...
- <newest commit subject>
```

If there is only one commit and it has a body, use the body as the description instead of a bullet list.

## Phase 6. Confirm with the User

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

Using the AskUserQuestion, ask the user what he wants to do with the PR/MR. Present the options:
- **yes** — continue to next phase.
- **edit title** — ask for a new title, then re-show the draft.
- **edit description** — ask for replacement description text, then re-show the draft.
- **cancel** — stop with "PR/MR creation cancelled."

## Phase 7. Create PR/MR

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
  "$TITLE" "$DESCRIPTION" "$USER_EMAIL"
```
If `create_mr.sh` exits non-zero, print its stderr output and stop.

The script assigns the PR/MR to the git user matching `$USER_EMAIL`.

On success the script outputs the MR web URL. Display:
```
MR/PR created: <web_url>
```

On failure (non-zero exit or empty output), print the raw error and stop.



