---
name: fix-gitlab-issue
description: >
  Use when the user provides a GitLab issue URL and asks to fix it, investigate it,
  work on it, or reproduce it. Trigger phrases: "fix this issue", "fix issue #N",
  "look at this gitlab issue", "work on this ticket", "work on this issue",
  followed by or combined with a GitLab URL or issue number.
version: 1.0.0
user-invocable: true
context: fork
---

# fix-gitlab-issue

Investigate a GitLab issue and produce a report with the root cause and suggested fix for the user to review.

If the user accepts the report, proceed with the proposed fix, commit and PR.

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

Compute the URL-encoded project path used in all GitLab API calls:
```bash
ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe=''))" "$PROJECT_PATH")
```

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

The script returns `{"issue":{...},"notes":[...]}`. Parse it to extract:
- `title` — from `.issue.title`
- `description` — from `.issue.description` (full text)
- `labels[]` — from `.issue.labels[].name`
- `milestone.title` — from `.issue.milestone.title` (if set)
- `assignees[].username` — from `.issue.assignees[].username`
- `notes[]` — from `.notes[]`, each comment's `body` and `author.username`, ascending by `created_at`

Display a compact summary to the user:
```
Issue #<IID>: <title>
Labels: <labels>  |  Milestone: <milestone>
<first 200 chars of description>...
Comments: <N> (<commenter names>)
```

## Phase 2 — Feasibility Assessment

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

## Phase 3 — Code Investigation (read-only, main repo)

Search and read code directly in the current repo checkout.

Use the issue's stack traces, error strings, component names, and function names to locate relevant code.

Read the relevant source files to:
- Identify the likely root cause at the code level (specific file:line).
- Understand the surrounding logic well enough to propose a concrete fix approach.
- Determine which files will need to change and roughly what the change entails.

This phase is **read-only** — no edits, no builds, no git operations.

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

Then use the `AskUserQuestion` tool to ask:

> "Root cause analysis complete. Do you want to see a proposed fix?"

Options:
- **Yes, propose a fix** — continue to Phase 5
- **Correct the analysis** — incorporate the user's feedback, revise the analysis, and re-ask this question
- **No / Abort** — stop here, no git operations

If the user selects **Correct the analysis**, apply their feedback, update the analysis report in place, and loop back to this question. If the user selects **No / Abort**, stop.

This phase is **read-only** — no edits, no builds, no git operations.

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

Then use the `AskUserQuestion` tool to ask:

> "Do you want to proceed with this fix?"

Options:
- **Proceed** — create the worktree and implement the fix
- **Revise the fix plan** — incorporate the user's feedback, revise the plan, and re-ask this question
- **Abort** — stop here, no git operations

If the user selects **Revise the fix plan**, apply their feedback, update the plan in place, and loop back to this question. If the user selects **Abort**, stop. Only continue to Phase 6 if the user explicitly approves.

This phase is **read-only** — no edits, no builds, no git operations.

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

**Issue comment (if root cause differs from the original issue description):**
If your root cause analysis adds material information beyond what the issue already states —
new specific details, a regression commit, a misidentified cause — post a comment via:
  curl -sf -X POST \
    -H "PRIVATE-TOKEN: $GITLAB_AI_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg b "<comment>" '{body: $b}')" \
    "$GITLAB_BASE/api/v4/projects/$ENC/issues/$ISSUE_IID/notes"
Keep the comment factual and brief. Reference the MR with !<MR_IID>. Skip if the issue
already correctly and fully describes the root cause.
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
   bash "$SKILL_DIR/scripts/create_mr.sh" \
     "$GITLAB_BASE" "$PROJECT_PATH" \
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

- `curl` returns empty or HTTP 4xx → print the raw response and stop with a clear error.
- Build fails repeatedly → document errors, stop, include them in the report.
- Tests fail after fix → include failure output in the report; do not create MR until user decides.
- Worktree path already exists → handled inline in Phase 6 (reuse or pick a different suffix).
- Push rejected (non-fast-forward) → do not force-push; inform the user and stop.
- MR creation fails → print the raw `create_mr.sh` output and stop; the worktree is preserved for retry.
