# ocudu-tools

Claude Code skills for working with [OCUDU](https://github.com/srsran/ocudu) — an open-source 5G CU/DU implementation. Covers instrumentation, observability, and diagnostics across the OCUDU stack.

## Skills

### analyze-ocudu-log

Analyses log files and console output from any OCUDU application. Activates automatically when you share a log file or unit test output containing OCUDU log lines.

It analyses the log in layers, starting with the cheap aggregate metrics and drilling into specific protocol layers only when anomalies are found.

**Covered layers:**
- `METRICS` — scheduler, MAC, PHY and executor KPI windows
- `SCHED` — slot decisions, PRACH/RACH events, HARQ chains
- `MAC` — cell lifecycle, pipeline timing
- `PHY` — LDPC processing latencies
- `RRC`, `F1AP`, `NGAP`, `E1AP` — control and user-plane signalling (stubs, populated over time)

**Supported log sources:**
- Log files from any OCUDU application: `gnb`, `du`, `cu`, `cu_cp`, `cu_up`
- Console output from unit tests or runtime
- Pasted log snippets

### fix-gitlab-issue

Autonomously investigates and fixes a GitLab issue in an isolated git worktree. Trigger: share a GitLab issue URL and ask to fix or investigate it.

The skill reads the issue and all comments, assesses whether a local fix is feasible, creates a worktree on a new branch, locates the relevant code, attempts to reproduce the bug, implements a fix, and validates it with targeted ninja/ctest. It then writes a report and—on your approval—commits, pushes, and opens an MR.

Requires `GITLAB_AI_TOKEN` (api-scoped personal access token) in your environment.

### fix-gitlab-mr

Investigates and fixes failing CI jobs on a GitLab MR. Trigger: share an MR URL and ask to fix or diagnose a failing pipeline.

The skill checks the latest pipeline status, lists failed jobs, lets you pick one, downloads and analyses the job log, then for fixable failures (compilation, linker, test, clang-tidy, clang-format) creates a worktree on the MR's source branch, applies a fix, validates it with targeted ninja/ctest, and proposes a commit back to the same branch. Infrastructure failures (timeouts, missing credentials, hardware) are reported but not acted on.

Requires `GITLAB_AI_TOKEN` (api-scoped personal access token) in your environment.

### synthesize-skill-update

Cleans up a personal branch before it is merged into `main`. Run it when reviewing a PR. It reads the diff, extracts generalisable knowledge, discards personal notes and overly specific hacks, edits the skill files in place, and produces a changelog entry with a list of what was kept and what was dropped.

## Installation

Add the marketplace, then install the plugin:

```
/plugin marketplace add frankist/ocudu-tools
/plugin install ocudu-tools
```

Or browse via `/plugin > Discover`.

## Usage

Skills trigger automatically from natural language. Examples:

**analyze-ocudu-log**
- "Why is RACH failing?" (with a log file open)
- "Analyze `/tmp/gnb.log`"
- Pasting console output from a failed unit test that includes OCUDU log lines

**fix-gitlab-issue**
- "Fix this issue: https://gitlab.com/ocudu/ocudu/-/issues/1234"
- "Look at issue #567 and fix it"

**fix-gitlab-mr**
- "The pipeline is failing on this MR: https://gitlab.com/ocudu/ocudu/-/merge_requests/618"
- "Fix the CI failure on !618"

**synthesize-skill-update**
- Run `/ocudu-tools:synthesize-skill-update` on your branch before opening a PR

## Contributing

### Branch model

| Branch | Purpose |
|---|---|
| `main` | Stable, shared skills — the version installed by users |
| `<name>` | Personal branch — local improvements, lessons learned, experimental notes |

### Proposing a skill update

1. Branch off `main`: `git checkout -b <your-name>`
2. Make your changes — add knowledge to layer files, refine instructions, fix gaps
3. Run `/ocudu-tools:synthesize-skill-update` to clean up your branch before submitting
4. Open a PR against `main`

### Review process

PRs are reviewed with the `synthesize-skill-update` skill, which extracts the generalisable knowledge from your branch, discards personal or overly specific notes, and merges the result cleanly into `main`. You will receive a summary of what was kept and what was left out.

## License

BSD 3-Clause — see [LICENSE](LICENSE).
