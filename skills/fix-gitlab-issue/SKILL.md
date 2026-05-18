---
name: fix-gitlab-issue
description: >
  Use when the user provides a GitLab issue URL and asks to fix it, investigate it,
  work on it, or reproduce it. Trigger phrases: "fix this issue", "fix issue #N",
  "look at this gitlab issue", "work on this ticket", "work on this issue",
  followed by or combined with a GitLab URL or issue number.
version: 1.0.0
user-invocable: true
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/get_context.sh:*), Bash(${CLAUDE_SKILL_DIR}/scripts/create_mr.sh:*)
---

# fix-gitlab-issue

Investigate a GitLab issue and produce a report with the root cause and suggested fix for the user to review.

If the user accepts the report, proceed with the proposed fix, commit and PR.

## Context

!`${CLAUDE_SKILL_DIR}/scripts/get_context.sh $ARGUMENTS`

## Phase 0 — Prerequisites

If the context script failed, stop — the error message already tells the user what to fix.

From the context output, assign:
- `GITLAB_HOST` — from `gitlab host:`
- `PROJECT_PATH` — from `project path:`
- `ISSUE_IID` — from `issue iid:`

## Phase 1 — Read Issue

The context output contains the parsed issue fields. Display a compact summary to the user:
```
Issue #<IID>: <title>
Labels: <labels>  |  Milestone: <milestone>
<first 200 chars of description>...
Comments: <N> (<commenter usernames>)
```

## Phase 2 — Feasibility Assessment

Read both the issue description and **comments**. Both can contain important information about the setup, actual diagnosis, a narrowed-down root cause, or additional log evidence.

Assess the issue:

| Factor | Questions to answer |
|---|---|
| Scope clarity | Is the bug reproducible from the description alone, or is it vague? |
| Local reproducibility | Does it need external hardware (SDR, RU, EPC/5GC), a live network, or a specific lab environment? |
| Code signal | Is there a stack trace, error message, component name, or log snippet pointing to a specific code location? |
| Fix complexity | Is the fix likely a targeted code change vs. a major architectural rework? |

Show the feasibility assessment to the user before proceeding.

If the issue is clearly **not actionable** (e.g. pure environment issue, requires hardware you can't simulate, completely underspecified), write a brief assessment and stop skill.

If local reproduction is not possible but a code-level fix is still feasible (e.g. logic bug visible from reading the code), note this and proceed — marking reproduction as "skipped (requires external setup)".

## Phase 3 — Code Investigation (read-only — no edits until Phase 6)

**Analyze logs.** If `analyze-ocudu-log` is available, check the issue and all its comments for log data:
- Inline OCUDU log output → invoke `analyze-ocudu-log` on it.
- CI job URL (e.g. `https://gitlab.com/<project>/-/jobs/<id>`) → invoke `analyze-ocudu-log` on it directly.

Tell the skill the reported symptom, affected component, and relevant error strings from the issue.

**Read code** in the current repo checkout, guided by log findings and the issue's stack traces, error strings, and component names. Identify the root cause (specific file:line), understand the fix scope, and list files that will change.

## Phase 4 — Report Analysis & Ask User

Report the analysis findings to the user:

```
## Analysis: Issue #<IID> — <title>

### Issue Summary
<2-4 sentences: what the issue reports, key clues from comments>

### Root Cause Hypothesis
<What is likely wrong at the code level — specific file:line, why it causes the reported symptom>

### Confidence
<high | medium | low> — <one sentence rationale>
```

If the root cause is unclear, do **not** speculate — report what's missing and ask the user for it via `AskUserQuestion` (e.g. a specific log, reproduction step, or configuration). Incorporate the answer, update the analysis, and re-ask.

Otherwise ask via `AskUserQuestion`: "Root cause analysis complete. Do you want to see a proposed fix?"

- **Yes, propose a fix** → Phase 5
- **Correct the analysis** → revise and re-ask
- **No / Abort** → stop

## Phase 5 — Propose Fix & Ask User

Present the fix plan:

```
## Proposed Fix: Issue #<IID> — <title>

### Fix
<What will be changed and why — rationale, alternatives considered>

### Files to Change
- `<path>` — <what changes>

### Branch
`fix/issue-<IID>-<slug>` based on `<base_branch>`

### Reproduction
<Will try to reproduce via: <test name/approach> — OR — will skip because <reason>>
```

Ask via `AskUserQuestion`: "Do you want to proceed with this fix?"

- **Proceed** → Phase 6
- **Revise the fix plan** → revise and re-ask
- **Abort** → stop

## Phase 6 — Create Worktree

**Determine base branch.** Default to `dev`. Override if:
- The issue description or milestone explicitly names a target branch.
- A label like `branch::xyz` is present.

**Create branch name:** `fix/issue-<IID>-<3-4-word-slug>` where the slug is a lowercase hyphenated summary of the issue title (e.g. `fix/issue-1234-null-ptr-in-scheduler`).

**Check for an existing worktree** at the target path before creating:
```bash
WORKTREE_PATH="/tmp/fix-$(basename "$PROJECT_PATH")-$ISSUE_IID"
git worktree list | grep "$WORKTREE_PATH"
```
If it already exists, reuse it (skip the `git worktree add` step). Otherwise create a new branch and worktree in one step:
```bash
git worktree add -b "fix/issue-$ISSUE_IID-<slug>" "$WORKTREE_PATH" "$BASE_BRANCH"
```

All subsequent file reads and edits must target paths under `$WORKTREE_PATH`, not the main repo checkout.

**Read project instructions.** Check `$WORKTREE_PATH/CLAUDE.md` for project-specific cmake flags, build requirements, and test conventions before configuring the build. If the file does not exist or does not mention cmake, use the defaults below.

**Create a dedicated build directory** in `/tmp` for this worktree to avoid collisions with the user's regular workflow:
```bash
BUILD_PATH="/tmp/fix-$(basename "$PROJECT_PATH")-$ISSUE_IID-build"
cmake -S "$WORKTREE_PATH" -B "$BUILD_PATH" -DCMAKE_BUILD_TYPE=RelWithDebInfo -G Ninja \
  -DLINKER=mold -DBUILD_TESTING=On -DCMAKE_CXX_COMPILER_LAUNCHER=
```
Pass `-DCMAKE_CXX_COMPILER_LAUNCHER=` (empty) to explicitly disable ccache even if the project enables it by default — the temporary build directory gets no cache hits and would only contaminate the user's ccache with throwaway objects.

## Phase 7 — Understand & Reproduce

**Attempt reproduction** following build and test conventions from `CLAUDE.md`:

- If a specific test or test target is mentioned → find it, build it, run it with ctest.
- If a runtime scenario is described → check if an existing test covers it, or write a minimal new unit test in the worktree.
- If external hardware is required → skip reproduction, note it, proceed to fix.

Document the result as one of:
- `Reproduced: yes — <evidence (test name, assertion, output snippet)>`
- `Reproduced: no — <what you tried and what happened instead>`
- `Reproduced: skipped — <reason (external hardware / insufficient description)>`

## Phase 8 — Implement Fix

Make the code changes in `$WORKTREE_PATH`. Follow all coding conventions from `CLAUDE.md` and the project's `.clang-format`.

**Build only the specific target(s) affected by the fix** — never build all targets. Identify the relevant target from the test file path or CMakeLists.txt and build it directly:
```bash
cmake --build "$BUILD_PATH" --target <specific_target> -- -j$(nproc)
```
Fix any compiler errors before proceeding.

**Run tests.** After a clean build, run only the relevant tests — never the full suite:
- The reproducing test (if created)
- The specific test target(s) built above (`ctest --test-dir "$BUILD_PATH" -R <pattern> --output-on-failure`)

If tests fail after the fix, document it honestly in the report — do **not** paper over failures or silently skip them.

## Phase 9 — Write Report

Write the report file at `$WORKTREE_PATH/ISSUE_FIX_REPORT.md`. Do not stage or commit this file — it is a work artifact, not part of the fix.

```
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
<output of: git -C "$WORKTREE_PATH" diff>

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
  <one-line summary>

  <paragraph: why this change, what it fixes>

  Assisted-by: Claude Code
  Fixes #<IID>

**MR title:** `<title>`

**MR description:**
  ## Root Cause
  <What was wrong and why — compiler/runtime mechanism, not just "the fix". Include any
  findings beyond what the original issue described: which commit introduced a regression,
  why a previous partial fix was insufficient, etc.>

  ## Summary
  <bullet points>

  ## Changes
  <files and what changed>

  Fixes #<IID>

**Issue comment** — if the analysis adds material information not in the original issue (regression commit, misidentified cause, new specific details), post a brief comment:
  glab issue note create "$ISSUE_IID" --message "<comment>" --repo "$GITLAB_HOST/$PROJECT_PATH"
Reference the MR with `!<MR_IID>`.
```

Show the full report inline to the user and **stop**. Wait for the user to explicitly approve before doing anything with git.

## Phase 10 — Commit, Push, Create MR (user-triggered only)

Only proceed when the user says "commit", "push", "create MR", "go ahead", or equivalent.

1. Stage changed files by name — never `git add -A`, and never stage `ISSUE_FIX_REPORT.md`:
   ```bash
   git -C "$WORKTREE_PATH" add <file1> <file2> ...
   ```
2. Commit (the `EOF` delimiter must be at column 0):
   ```bash
   git -C "$WORKTREE_PATH" commit -m "$(cat <<'EOF'
<one-line summary>

<paragraph body>

Assisted-by: Claude Code
Fixes #<IID>
EOF
)"
   ```
3. Push:
   ```bash
   git -C "$WORKTREE_PATH" push -u origin fix/issue-<IID>-<slug>
   ```
4. Create MR — store title and description in variables to handle special characters and newlines:
   ```bash
   MR_TITLE="<MR title>"
   MR_DESC="$(cat <<'EOF'
<MR description>
EOF
)"
   bash "$CLAUDE_SKILL_DIR/scripts/create_mr.sh" \
     "$WORKTREE_PATH" \
     "fix/issue-<IID>-<slug>" "$BASE_BRANCH" \
     "$MR_TITLE" "$MR_DESC"
   ```
   Print the returned URL.
5. Ask the user whether to clean up the worktree and build directory, then if confirmed:
   ```bash
   git worktree remove "$WORKTREE_PATH"
   rm -rf "$BUILD_PATH"
   ```

## Error handling

- `glab` command fails → print the raw output and stop with a clear error.
- Build fails repeatedly → document errors, stop, include them in the report.
- Tests fail after fix → include failure output in the report; do not create MR until user decides.
- Worktree path already exists → handled inline in Phase 6 (reuse or pick a different suffix).
- Push rejected (non-fast-forward) → do not force-push; inform the user and stop.
- MR creation fails → print the raw `create_mr.sh` output and stop; the worktree is preserved for retry.
