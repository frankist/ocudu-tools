---
name: safe-commit
description: Create well-formatted git commits following conventional commit standards. Trigger phrases can be "commit my changes", "commit the changes you made".
version: 1.0.0
user-invocable: true
disable-model-invocation: true
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

The script already aborts if the current branch is main, and already stages tracked-file changes.

1. If the context script printed a `worktree path`, use it for all subsequent git commands by prefixing them with `-C <worktree-path>`.
2. If the context output contains a `changes` section, only untracked files (lines starting with `??`) need a decision — use `AskUserQuestion` to show the listed files and ask how to proceed:
     - **Include them** — stage those files (`git add`) before continuing
     - **Ignore them** — continue without staging them
     - **Abort** — stop and let the user handle staging manually; exit with a message listing the files.
3. Delegate the commit message draft to a dedicated `Explore` subagent (via the `Agent` tool, `model: "haiku"`) so the diff never enters this conversation's context. Prompt: `Read and follow ${CLAUDE_SKILL_DIR}/references/subagent_prompt.md. Worktree path: <path, or "none — use repo root">.`
4. Show the returned message's full text in the `preview` field of the "Looks good" option via `AskUserQuestion`, and ask the user if it's correct or needs changes. If changes are requested, edit the message directly or send the subagent back for another draft.
5. Create the commit. Confirm success from the `git commit` output's own summary line only.

## Commit Format
`<type>(<scope>): <description>`, optional body, optional footer. Type ∈ `feat | fix | docs | style | refactor | test | chore`. Example:
```
feat(auth): add password reset functionality

- Add forgot password form
- Implement email verification flow
- Add password reset endpoint
```
