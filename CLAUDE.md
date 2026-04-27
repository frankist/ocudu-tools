# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A Claude Code plugin (`ocudu-tools`) containing skills for working with [OCUDU](https://github.com/srsran/ocudu) — an open-source 5G CU/DU implementation. Skills cover instrumentation, observability, and diagnostics.

## Repository structure

```
.claude-plugin/
  plugin.json          # Plugin manifest (name, description, author)
  marketplace.json     # Marketplace listing pointing to frankist/ocudu-tools on GitHub
skills/
  analyze-ocudu-log/
    SKILL.md           # Skill definition and instructions
    references/
      analysis-guide.md          # Detailed analysis steps
      layers/                    # Per-layer reference files (metrics, sched, mac, phy, rrc, ...)
  fix-gitlab-issue/
    SKILL.md           # Skill for autonomously investigating and fixing a GitLab issue
    scripts/
      fetch_issue.sh   # Fetch issue metadata + comments
      create_mr.sh     # Open an MR for the fix
  fix-gitlab-mr/
    SKILL.md           # Skill for diagnosing and fixing failing GitLab MR CI jobs
    scripts/
      fetch_mr.sh              # Fetch MR metadata + recent pipelines
      fetch_pipeline_jobs.sh   # List jobs for a pipeline
      fetch_job_log.sh         # Download job trace to a local file
  synthesize-skill-update/
    SKILL.md           # Skill for synthesizing user-branch changes into main
```

## Skills

### analyze-ocudu-log

Triggered automatically when a user shares a `.log` file or OCUDU-formatted console output. Analyses logs in layers: starts with METRICS (cheap), then drills into SCHED, MAC, PHY, RRC, F1AP, NGAP, E1AP only when anomalies are found.

Layer knowledge lives in `references/layers/*.md` — these files grow over time as new patterns are discovered. After each analysis, append new generalisable findings to the relevant layer file's **Accumulated knowledge** section.

### fix-gitlab-issue

Triggered when the user provides a GitLab issue URL and asks to fix, investigate, or reproduce it. Reads the issue and comments, assesses feasibility, creates a git worktree on a new branch, searches for the relevant code, attempts reproduction, implements a fix, validates it with targeted ninja/ctest, and writes a report. On user approval, commits, pushes, and opens an MR.

Scripts under `scripts/` wrap the GitLab API calls. `GITLAB_AI_TOKEN` env var must be set (api-scoped personal access token).

### fix-gitlab-mr

Triggered when the user provides a GitLab MR URL and asks to investigate or fix a failing CI pipeline. Fetches the MR, identifies the latest (or a chosen earlier) pipeline, lists failed jobs, lets the user pick one, downloads and analyses the job log, then—for fixable failures (compilation, test, linting, format)—creates a git worktree on the MR's source branch, applies a fix, validates it with targeted ninja/ctest, and proposes a commit back to the same branch.

Scripts under `scripts/` wrap the GitLab API calls. `GITLAB_AI_TOKEN` env var must be set (api-scoped personal access token).

### synthesize-skill-update

Run by the maintainer when reviewing a PR from a user branch. Reads the diff against `main`, extracts generalisable knowledge, discards personal notes and overly specific hacks, and edits the skill files in place. Produces a changelog entry and a list of discarded items.

## Contributing workflow

- `main` — stable, shared skills; protected, requires PR + approval to merge
- `<name>` — personal branch for local improvements and lessons learned

Before opening a PR: run `/ocudu-tools:synthesize-skill-update` on your branch to clean it up first.

## Extending the plugin

To add a new skill, create `skills/<skill-name>/SKILL.md` with frontmatter (`name`, `description`, `version`) and the skill instructions. No build step or registration needed — Claude Code discovers skills from the directory structure defined in `plugin.json`.
