---
name: fix-gitlab-mr
description: >
  Use when the user provides a GitLab MR URL and asks to investigate, fix, or diagnose
  failing CI pipeline jobs. Trigger phrases: "fix this MR", "CI is failing on", "the
  pipeline failed", "fix the failing job", "look at this MR", followed by or combined
  with a GitLab MR URL or MR number.
version: 1.0.0
---

# fix-gitlab-mr

Investigate and fix failing CI jobs on a GitLab MR, then propose a commit to the same MR branch.

## Self-improvement

This skill may edit its own `SKILL.md` and supporting scripts at any time to improve itself. Worthwhile improvements include: sharper failure classification, better grep patterns for extracting errors from logs, more targeted build/test commands, new failure categories encountered in practice, faster or cheaper API access patterns, and anything that reduces unnecessary token usage or work. After editing, note what changed and why in a brief inline comment above the changed section. No user approval is needed for self-edits — they are part of normal skill execution.

## Phase 0 — Prerequisites

**Check token.** Run:
```bash
echo "${GITLAB_AI_TOKEN:-MISSING}"
```
If the output is `MISSING`, stop and tell the user:
> `GITLAB_AI_TOKEN` is not set. Add it to `~/.zshrc` or `~/.bashrc`:
> ```
> export GITLAB_AI_TOKEN=<your-personal-access-token>
> ```
> Create a token at https://gitlab.com/-/user_settings/personal_access_tokens with `api` scope.

**Parse the URL.** From the user-provided URL (e.g. `https://gitlab.com/ocudu/ocudu/-/merge_requests/618`), extract:
- `GITLAB_HOST` — e.g. `gitlab.com`
- `GITLAB_BASE` — e.g. `https://gitlab.com`
- `PROJECT_PATH` — e.g. `ocudu/ocudu`
- `MR_IID` — numeric MR ID (e.g. `618`)

Find the `SKILL_DIR` (directory containing this SKILL.md) so scripts can be invoked with absolute paths.

## Phase 1 — Fetch MR and Pipelines

Run:
```bash
bash "$SKILL_DIR/scripts/fetch_mr.sh" "$GITLAB_BASE" "$PROJECT_PATH" "$MR_IID"
```

From the returned JSON extract:
- `mr.title` — MR title
- `mr.source_branch` — the branch to check out and push to
- `mr.target_branch` — the merge target (used as the base for the worktree)
- `mr.web_url`
- `pipelines[]` — list of recent pipelines, each with `id`, `status`, `web_url`, `sha`

Display a compact summary:
```
MR !<IID>: <title>
Source: <source_branch> → <target_branch>
URL: <web_url>
```

## Phase 2 — Pipeline Status Gate

Identify the **latest pipeline** (first element of `pipelines[]`).

| Latest pipeline status | Action |
|---|---|
| `success` | Tell the user: "The latest pipeline passed. Nothing to fix." Offer two options: (1) close here, (2) pick an earlier pipeline to investigate. If the user picks (2), let them choose from the list and continue from Phase 3. |
| `running` or `pending` | Fetch the jobs for this pipeline (Phase 3 script) and check if any have `status == "failed"` already. If yes: tell the user which jobs have already failed and offer two options: (1) stop here, (2) pick one of the already-failed jobs to investigate now. If no jobs have failed yet: tell the user the pipeline is still running with no failures yet and offer two options: (1) stop here, (2) pick an earlier pipeline to investigate. |
| `failed` or `canceled` | Continue to Phase 3. |
| No pipelines at all | Tell the user: "No pipelines found for this MR." Stop. |

When re-analyzing an earlier pipeline, make clear which pipeline (ID + short SHA) you are investigating.

## Phase 3 — Select Failed Job

Run:
```bash
bash "$SKILL_DIR/scripts/fetch_pipeline_jobs.sh" "$GITLAB_BASE" "$PROJECT_PATH" "$PIPELINE_ID"
```

From the job list, extract all jobs where `status == "failed"`.

Present the failed jobs as a numbered list:
```
Failed jobs in pipeline #<PIPELINE_ID>:
  1. <job_name>  (stage: <stage>, id: <job_id>)
  2. ...
```

Ask the user: "Which job would you like to investigate? (enter a number)"

Wait for the user's selection, then proceed with that `job_id` and `job_name`.

## Phase 4 — Download and Analyze Job Log

**Download the log:**
```bash
LOG_FILE="/tmp/mr-${MR_IID}-job-${JOB_ID}.log"
bash "$SKILL_DIR/scripts/fetch_job_log.sh" "$GITLAB_BASE" "$PROJECT_PATH" "$JOB_ID" "$LOG_FILE"
```

**Find the failure.** Logs can be large — never read the whole file. Work from the end:

1. Check the last 200 lines for the primary failure signal:
   ```bash
   tail -200 "$LOG_FILE"
   ```
2. Search for common failure patterns to narrow down the type:
   ```bash
   grep -n "error:" "$LOG_FILE" | tail -30
   grep -n "FAILED" "$LOG_FILE" | tail -20
   grep -n "undefined reference" "$LOG_FILE" | tail -10
   grep -n "warning: " "$LOG_FILE" | grep -i "clang-tidy\|error" | tail -20
   ```

**Classify the failure** into one of these categories:

| Category | Key signals in log |
|---|---|
| **Compilation error** | `error:` from `g++`/`clang++`, file path with line number |
| **Linker error** | `undefined reference to`, `ld: error` |
| **Test failure** | `FAILED` from ctest, `Assertion`, `Expected:`, `ASSERT_` macros |
| **Clang-tidy** | `clang-tidy`, `[clang-`, `warning treated as error` |
| **Clang-format** | `clang-format`, lines starting with `+`/`-` diff output |
| **CMake/config** | `CMake Error`, `Could not find` |
| **Infra/network** | `Connection refused`, `Timeout`, `no space left on device`, Docker errors |

For infra/network failures, write a brief assessment and **stop** — these are not fixable by a code change.

For all other categories, continue to Phase 5.

## Phase 5 — Create Worktree on MR Branch

**Check if worktree already exists:**
```bash
git worktree list
```
If a worktree for this MR already exists at the expected path, reuse it (skip the `git worktree add` step).

**Create the worktree on the MR's source branch:**
```bash
WORKTREE_PATH="/tmp/fix-mr-${MR_IID}"
git fetch origin "${MR_SOURCE_BRANCH}"
git worktree add "$WORKTREE_PATH" "origin/${MR_SOURCE_BRANCH}"
# Set the branch to track the remote so we can push later
git -C "$WORKTREE_PATH" checkout -B "${MR_SOURCE_BRANCH}" "origin/${MR_SOURCE_BRANCH}"
```

All subsequent file reads and edits must target paths under `$WORKTREE_PATH`.

**Configure the build.** Never use the user's existing `build/` or `build_plugins/` directories.
```bash
BUILD_PATH="/tmp/fix-mr-${MR_IID}-build"
cmake -S "$WORKTREE_PATH" -B "$BUILD_PATH" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -G Ninja \
  -DLINKER=mold \
  -DBUILD_TESTING=On
```
**Do NOT pass** `-DCMAKE_CXX_COMPILER_LAUNCHER=ccache`. The worktree source lives at a different absolute path than the user's checkout, so every object would be a cache miss and would pollute the user's ccache with stale entries.

## Phase 6 — Implement Fix

**Understand the failure root cause.** Use the log analysis from Phase 4 to locate the exact file(s) and line(s) involved. Read those files from the worktree:
```bash
# e.g. find which target owns the failing translation unit
grep -r "<failing_file_basename>" "$WORKTREE_PATH" --include="CMakeLists.txt" -l
```

Apply code fixes **in the worktree** following the project's coding conventions (from `$WORKTREE_PATH/CLAUDE.md` and `.clang-format`).

**Failure-type guidance:**

- **Compilation error**: Read the file at the reported line. Understand what changed in the MR that caused it. Fix only what the error requires — do not refactor.
- **Linker error**: Find the missing symbol. Either add the missing implementation or add the missing library to the CMakeLists.
- **Test failure**: Read the test and the asserted code. Determine whether the code or the test expectation is wrong. Fix accordingly.
- **Clang-tidy**: Address each reported diagnostic. Prefer suppressing with `// NOLINT(...)` only when the diagnostic is a false positive and cannot be fixed cleanly.
- **Clang-format**: Run the formatter on the affected files:
  ```bash
  clang-format-18 -i <files>
  ```

**Build only the affected target.** Identify the CMake target from the failing file path, then:
```bash
cmake --build "$BUILD_PATH" --target <specific_target> -- -j$(nproc)
```
Fix compiler errors iteratively. Do not proceed to testing until the build is clean.

**Run all test targets that failed in the CI job.** From the log analysis in Phase 4, collect every distinct test binary that appeared in the FAILED list (e.g. `common_scheduler_test`, `scheduler_test`, `du_high_tester`). Build and run each one:
```bash
cmake --build "$BUILD_PATH" --target <test_target_1> <test_target_2> ... -- -j$(nproc)
ctest --test-dir "$BUILD_PATH" -R "^(test_target_1|test_target_2|...)$" --output-on-failure -j$(nproc)
```
Do not narrow the pattern further — if the CI ran the whole binary and it failed, run the whole binary. Never run the full suite beyond what failed.

If tests still fail after the fix, document it honestly in the report — do not hide failures or skip them silently.

## Phase 7 — Write Report

Write the report file at `$WORKTREE_PATH/MR_FIX_REPORT.md`:

```markdown
# Fix Report: MR !<IID> — <title>

**URL:** <mr web_url>
**Pipeline:** #<PIPELINE_ID> — <pipeline web_url>
**Job:** <job_name> (id: <JOB_ID>)
**Assessed:** <date>

---

## Failure Summary

**Category:** <compilation | linker | test | clang-tidy | clang-format | cmake>

<2-4 sentence summary of what the job reported, quoting the key error message(s)>

## Root Cause

<What was wrong at the code level — specific file:line where the defect lives. If the MR introduced a regression, name the commit or the change that caused it.>

## Fix

<What was changed and why — rationale for the chosen approach, alternatives rejected>

## Changed Files

```diff
<output of: git -C $WORKTREE_PATH diff>
```

## Build and Test Results

| Step | Result |
|---|---|
| Build target `<target>` | PASS / FAIL |
| Test `<pattern>` | PASS / FAIL (N/N passed) |

## Confidence

**Level:** high | medium | low
**Rationale:** <why>

---

## Suggested Commit

**Branch:** `<source_branch>` (pushed to the same MR)

**Commit message:**
```
<one-line summary>

<paragraph: why this change, what it fixes>

Assisted-by: Claude Code
```
```

Show the full report inline to the user and **stop**. Wait for explicit approval before touching git.

## Phase 8 — Commit and Push (user-triggered only)

Proceed only when the user says "commit", "push", "go ahead", or equivalent.

1. Stage changed files by name (never `git add -A` or `git add .`):
   ```bash
   git -C "$WORKTREE_PATH" add <file1> <file2> ...
   ```
2. Commit:
   ```bash
   git -C "$WORKTREE_PATH" commit -m "$(cat <<'EOF'
   <one-line summary>

   <paragraph body>

   Assisted-by: Claude Code
   EOF
   )"
   ```
3. Push to the existing MR branch:
   ```bash
   git -C "$WORKTREE_PATH" push origin "${MR_SOURCE_BRANCH}"
   ```
   Print the MR URL so the user can check the new pipeline.
4. Clean up worktree and build dir:
   ```bash
   git worktree remove "$WORKTREE_PATH"
   rm -rf "$BUILD_PATH"
   ```

## Error handling

- `curl` returns empty or HTTP 4xx → print the raw response and stop with a clear error.
- Build fails repeatedly (more than 2 attempts) → stop, include all error output in the report.
- Tests fail after fix → include failure output in report; do not push until user decides.
- Worktree path already exists → reuse if the branch matches; otherwise append `-2` suffix and create fresh.
- `git push` is rejected (non-fast-forward) → tell the user the MR branch has diverged and ask them to rebase manually before retrying.
