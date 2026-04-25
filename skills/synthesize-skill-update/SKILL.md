---
name: synthesize-skill-update
description: Use when reviewing a user branch or PR that proposes changes to skill files. Synthesizes useful knowledge from the branch into a clean, general update ready for main.
version: 1.0.0
---

# Synthesize Skill Update

You are the maintainer of this repository of Claude skills and tools. Review the changes in this branch compared to `main`. Your task:

1. Identify new useful knowledge, patterns, examples, and instructions.
2. Remove duplicates, personal notes, overly specific hacks, and contradictions.
3. Merge the useful parts into the skill in a clean, general form.
4. Preserve the existing structure and style.
5. If instructions conflict, propose the safest/default behavior.
6. Produce: updated skill files, a changelog entry, and a list of discarded or unresolved items.

## How to run

Check out the user branch (or the PR branch) and invoke this skill:

```
git checkout <user-branch>
/ocudu-tools:synthesize-skill-update
```

## Output

Produce three things:

1. **Updated skill files** — edit the relevant `SKILL.md` and `references/` files in place with the synthesized changes.
2. **Changelog entry** — a short bullet summarising what was added, changed, or removed, suitable for appending to a `CHANGELOG.md` or PR description.
3. **Discarded / unresolved items** — a brief list of changes from the user branch that were not merged and why (too specific, duplicate, contradicts existing guidance, needs more evidence, etc.).
