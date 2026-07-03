---
name: safe-commit
description: Create well-formatted git commits following conventional commit standards. Trigger phrases can be "commit my changes", "commit the changes you made".
version: 1.0.0
user-invocable: true
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/get_context.sh:*), Bash(git commit *), Bash(git -C * commit *), Bash(git add *), Bash(git -C * add *), Bash(git diff *), Bash(git -C * diff *)
---

# Git Commit Skill

Create well-formatted git commits following conventional commit standards.

## Usage
```
/safe-commit [path-or-branch]
```

The optional argument can be a worktree path or a worktree branch name. The context script resolves it to a worktree path and prints it; if the argument is invalid or the branch has no worktree the script exits with an error.

## Context

!`${CLAUDE_SKILL_DIR}/scripts/get_context.sh $ARGUMENTS`

## Behavior

1. If the context script printed a `worktree path`, use it for all subsequent git commands by prefixing them with `-C <worktree-path>`.
2. Compare the current branch against the main branch from the context output. Abort with an error if they match — commits directly to main are not allowed.
3. If the context output contains a `changes` section, classify each entry by its porcelain `XY` code (`X` = staged/index state, `Y` = unstaged/worktree state, `??` = untracked):
   - **Tracked changes** (any non-`??` line — whether already staged like `M `, unstaged like ` M`, or both like `MM`) — stage them with `git add` before continuing. This is a no-op for already-staged files and pulls in any unstaged hunks of partially-staged files, so the commit reflects the full working state.
   - **Untracked files** (lines starting with `??`) — use `AskUserQuestion` to show the listed files and ask how to proceed:
     - **Include them** — stage those files (`git add`) before continuing
     - **Ignore them** — continue without staging them
     - **Abort** — stop and let the user handle staging manually; exit with a message listing the files.
4. Now that staging is resolved (step 3), run `git diff --staged --shortstat` to judge the diff size (single summary line — cheaper than per-file `--stat`). Then draft the commit message, basing it solely on what the diff shows — do not mention intermediate steps, self-corrections, or bugs introduced and fixed within the same staged set of changes:
   - **Small diff** — read it inline (prefer `git diff --staged -U1`, skip noise files like lockfiles/generated/vendored/`*.min.*`/binaries) and draft the message yourself.
   - **Large diff** — delegate to a dedicated `Explore` subagent (via the `Agent` tool) so the diff never enters this conversation's context — only the agent's proposed message returns. Run it on the cheapest available model (`model: "haiku"`). Give the agent, in its prompt:
     - The worktree path (if any) so it prefixes git commands with `-C <worktree-path>`.
     - The instruction to inspect the staged changes frugally: start with `git diff --staged --stat`, read full diffs only for files that inform the message (`git diff --staged -U1 -- <file>...`), and skip full diffs of noise files (lockfiles, generated/vendored code, `*.min.*`, large data/binaries).
     - The commit-message rules (Commit Format, Types below; and the "base it solely on the diff" rule above).
     - Instruction to return ONLY the proposed commit message text (no diff, no file dumps, no commentary).
5. Take the message the subagent returned and, using AskUserQuestion, show its full text in the `preview` field of the "Looks good" option, then ask the user if the commit message is correct or changes are required. If changes are requested, edit the message directly or send the subagent back for another draft.
6. Create the commit. Confirm success from the `git commit` output's own summary line only — do NOT re-inspect with `git show`, `git log -p`, or `git diff HEAD~1`, which re-dump the full diff into context.

## Commit Format
`<type>(<scope>): <description>`, optional body, optional footer. Type ∈ `feat | fix | docs | style | refactor | test | chore`. Example:
```
feat(auth): add password reset functionality

- Add forgot password form
- Implement email verification flow
- Add password reset endpoint
```
