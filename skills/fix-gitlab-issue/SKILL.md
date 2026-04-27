---
name: fix-gitlab-issue
description: >
  Use when the user provides a GitLab issue URL and asks to fix it, investigate it,
  work on it, or reproduce it. Trigger phrases: "fix this issue", "fix issue #N",
  "look at this gitlab issue", "work on this ticket", "work on this issue",
  followed by or combined with a GitLab URL or issue number.
version: 1.0.0
---

# fix-gitlab-issue

Autonomously investigate and fix a GitLab issue in an isolated git worktree, then produce a report for the user to review before any git operations.

## Phase 0 — Prerequisites

**Check token.** Run:
```bash
echo "${GITLAB_AI_TOKEN:-MISSING}"
```
If the output is `MISSING`, stop immediately and tell the user:
> `GITLAB_AI_TOKEN` is not set. Add the following to your shell profile (`~/.zshrc` or `~/.bashrc`):
> ```
> export GITLAB_AI_TOKEN=<your-personal-access-token>
> ```
> Create a token at https://gitlab.com/-/user_settings/personal_access_tokens with `api` scope.

**Parse the URL.** From the user-provided URL (e.g. `https://gitlab.com/ocudu/ocudu/-/issues/1234`), extract:
- `GITLAB_HOST` — e.g. `gitlab.com`
- `GITLAB_BASE` — e.g. `https://gitlab.com`
- `PROJECT_PATH` — e.g. `ocudu/ocudu`
- `ISSUE_IID` — the numeric issue ID (e.g. `1234`)

**Detect the current repo's remote** (for context only — the issue project may differ):
```bash
git remote get-url origin 2>/dev/null || echo "(no remote)"
```

Find the `SKILL_DIR` (the directory containing this SKILL.md) so scripts can be invoked with absolute paths.

## Phase 1 — Read Issue

Run:
```bash
bash "$SKILL_DIR/scripts/fetch_issue.sh" "$GITLAB_BASE" "$PROJECT_PATH" "$ISSUE_IID"
```

Parse the returned JSON to extract:
- `title`
- `description` (full text)
- `labels[]` (names)
- `milestone.title` (if set)
- `assignees[].username`
- `notes[]` — each comment's `body` and `author.username`, ordered by `created_at`

Display a compact summary to the user:
```
Issue #<IID>: <title>
Labels: <labels>  |  Milestone: <milestone>
<first 200 chars of description>...
Comments: <N> (<commenter names>)
```

## Phase 2 — Feasibility Assessment

Before creating a worktree, assess the issue:

| Factor | Questions to answer |
|---|---|
| Scope clarity | Is the bug reproducible from the description alone, or is it vague? |
| Local reproducibility | Does it need external hardware (SDR, RU, EPC/5GC), a live network, or a specific lab environment? |
| Code signal | Is there a stack trace, error message, component name, or log snippet pointing to a specific code location? |
| Fix complexity | Is the fix likely a targeted code change vs. a major architectural rework? |

If the issue is clearly **not actionable** (e.g. pure environment issue, requires hardware you can't simulate, completely underspecified), write a brief assessment and stop — do not create a worktree.

If local reproduction is not possible but a code-level fix is still feasible (e.g. logic bug visible from reading the code), note this and proceed — marking reproduction as "skipped (requires external setup)".

## Phase 3 — Create Worktree

**Determine base branch.** Default to `dev`. Override if:
- The issue description or milestone explicitly names a target branch.
- A label like `branch::xyz` is present.

**Create branch name:** `fix/issue-<IID>-<3-4-word-slug>` where the slug is a lowercase hyphenated summary of the issue title (e.g. `fix/issue-1234-null-ptr-in-scheduler`).

**Create the worktree:**
```bash
WORKTREE_PATH="/tmp/fix-$(basename "$PROJECT_PATH")-$ISSUE_IID"
git worktree add "$WORKTREE_PATH" "$BASE_BRANCH"
```

All subsequent file reads and edits must target paths under `$WORKTREE_PATH`, not the main repo checkout.

**Create a dedicated build directory** in `/tmp` for this worktree to avoid collisions with the user's regular workflow:
```bash
BUILD_PATH="/tmp/fix-$(basename "$PROJECT_PATH")-$ISSUE_IID-build"
cmake -S "$WORKTREE_PATH" -B "$BUILD_PATH" -DCMAKE_BUILD_TYPE=RelWithDebInfo -G Ninja \
  -DLINKER=mold -DBUILD_TESTING=On
```
**Never use ccache** (omit `-DCMAKE_CXX_COMPILER_LAUNCHER=ccache`) — the worktree build is isolated and ccache pollution would slow the user's main builds.

## Phase 4 — Understand & Reproduce

**Search for relevant code.** Use the issue's stack traces, component names, function names, and error strings to grep the worktree:
```bash
grep -r "<symbol>" "$WORKTREE_PATH" --include="*.cpp" --include="*.h" -l
```

**Read `CLAUDE.md`** (at `$WORKTREE_PATH/CLAUDE.md`) for project-specific build and test instructions. Follow those instructions exactly for all build and test commands.

**Attempt reproduction:**

- If a specific test or test target is mentioned → find it, build it, run it with ctest.
- If a runtime scenario is described → check if an existing test covers it, or write a minimal new unit test in the worktree.
- If external hardware is required → skip reproduction, note it, proceed to fix.

Document the result as one of:
- `Reproduced: yes — <evidence (test name, assertion, output snippet)>`
- `Reproduced: no — <what you tried and what happened instead>`
- `Reproduced: skipped — <reason (external hardware / insufficient description)>`

## Phase 5 — Implement Fix

Make the code changes in `$WORKTREE_PATH`. Follow all coding conventions from `CLAUDE.md` and the project's `.clang-format`.

**Build only the specific target(s) affected by the fix** — never build all targets. Identify the relevant target from the test file path or CMakeLists.txt and build it directly:
```bash
cmake --build "$BUILD_PATH" --target <specific_target>
```
Fix any compiler errors before proceeding.

**Run tests.** After a clean build, run only the relevant tests — never the full suite:
- The reproducing test (if created)
- The specific test target(s) built above (`ctest --test-dir "$BUILD_PATH" -R <pattern> --output-on-failure`)

If tests fail after the fix, document it honestly in the report — do **not** paper over failures or silently skip them.

## Phase 6 — Write Report

Write the report file at `$WORKTREE_PATH/ISSUE_FIX_REPORT.md`:

```markdown
# Fix Report: Issue #<IID> — <title>

**URL:** <issue URL>  
**Labels:** <labels>  
**Assessed:** <date>

---

## Issue Summary
<2-4 sentence summary of what the issue reports, key details from comments>

## Root Cause
<What was wrong at the code level — specific file:line where the defect lives>

## Reproduction
**Status:** reproduced | not reproduced | skipped (<reason>)  
<Steps taken, test name, output snippet or failure message>

## Fix
<What was changed and why — rationale for the chosen approach, alternatives rejected>

## Changed Files
```diff
<output of: git -C $WORKTREE_PATH diff>
```

## Test Results
| Test | Result |
|---|---|
| <test name> | PASS / FAIL |

## Confidence
**Level:** high | medium | low  
**Rationale:** <why>

---

## Suggested Next Steps

**Branch:** `fix/issue-<IID>-<slug>`  
**Base:** `<base_branch>`

**Commit message:**
```
<one-line summary>

<paragraph: why this change, what it fixes>

Fixes #<IID>
```

**MR title:** `<title>`

**MR description:**
```markdown
## Summary
<bullet points>

## Changes
<files and what changed>

Fixes #<IID>
```
```

Show the full report inline to the user and **stop**. Wait for the user to explicitly approve before doing anything with git.

## Phase 7 — Commit, Push, Create MR (user-triggered only)

Only proceed when the user says "commit", "push", "create MR", "go ahead", or equivalent.

1. Stage changed files by name (never `git add -A`):
   ```bash
   git -C "$WORKTREE_PATH" add <file1> <file2> ...
   ```
2. Commit:
   ```bash
   git -C "$WORKTREE_PATH" commit -m "$(cat <<'EOF'
   <one-line summary>

   <paragraph body>

   Fixes #<IID>
   EOF
   )"
   ```
3. Push:
   ```bash
   git -C "$WORKTREE_PATH" push -u origin fix/issue-<IID>-<slug>
   ```
4. Create MR:
   ```bash
   bash "$SKILL_DIR/scripts/create_mr.sh" \
     "$GITLAB_BASE" "$PROJECT_PATH" \
     "fix/issue-<IID>-<slug>" "$BASE_BRANCH" \
     "<MR title>" "<MR description>"
   ```
   Print the returned URL.
5. Clean up worktree and build dir:
   ```bash
   git worktree remove "$WORKTREE_PATH"
   rm -rf "$BUILD_PATH"
   ```

## Error handling

- `curl` returns empty or HTTP 4xx → print the raw response and stop with a clear error.
- Build fails repeatedly → document errors, stop, include them in the report.
- Tests fail after fix → include failure output in the report; do not create MR until user decides.
- Worktree path already exists → use `git worktree list` to check, then either reuse or pick a different suffix.
