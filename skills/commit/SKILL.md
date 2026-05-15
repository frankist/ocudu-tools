---
name: commit
description: Create well-formatted git commits following conventional commit standards. Trigger phrases can be "commit my changes", "commit the changes you made".
version: 1.0.0
user-invocable: true
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/get_context.sh:*), Bash(git commit *), Bash(git status *), Bash(git -C * status *), Bash(git diff *), Bash(git -C * diff *)
---

# Git Commit Skill

Create well-formatted git commits following conventional commit standards.

## Usage
```
/commit [path-or-branch]
```

The optional argument can be a worktree path or a worktree branch name. The context script resolves it to a worktree path and prints it; if the argument is invalid or the branch has no worktree the script exits with an error.

## Context

!`${CLAUDE_SKILL_DIR}/scripts/get_context.sh $ARGUMENTS`

## Behavior

1. If the context script printed a `worktree path`, use it for all subsequent git commands by prefixing them with `-C <worktree-path>`.
2. Compare the current branch against the main branch from the context output. Abort with an error if they match — commits directly to main are not allowed.
3. Run `git status --porcelain` and abort with an error if there are unstaged changes (lines starting with ` M`, ` D`, ` R`, ` C`) or untracked files (lines starting with `??`). Tell the user to stage all intended changes before running `/commit`.
4. Analyze staged changes with `git diff --staged`
5. Generate a conventional commit message. Base it solely on what the diff shows — do not mention intermediate steps, self-corrections, or bugs introduced and fixed within the same staged set of changes. Using AskUserQuestion, show the full proposed commit message text in the `preview` field of the "Looks good" option, then ask user if the commit message is correct or changes are required.
6. Create the commit with proper formatting

## Commit Format
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

## Types
- feat: New feature
- fix: Bug fix
- docs: Documentation changes
- style: Code style changes
- refactor: Code refactoring
- test: Adding or modifying tests
- chore: Maintenance tasks

## Example Output
```
feat(auth): add password reset functionality

- Add forgot password form
- Implement email verification flow
- Add password reset endpoint
```
