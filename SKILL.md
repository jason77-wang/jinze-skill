---
name: jinze
description: >
  Assist the jinze team with the linux-kunpeng (Ubuntu Kunpeng, Huawei ARM64)
  kernel. Dispatches to sub-skills for evaluating a provided patchlist and for
  reviewing a customer's merge request against the jinze kernel. Use when the
  user mentions jinze, kunpeng, a patchlist to evaluate, or a merge request /
  MR / branch to review for the jinze kernel.
user-invocable: true
---

# jinze

Umbrella skill for the jinze team's `linux-kunpeng` kernel work. It routes the
request to a focused sub-skill and provides shared context about the kernel.

The jinze kernel is an Ubuntu-derived kernel (package `linux-kunpeng`, based on
Noble / 6.8) for the Huawei Kunpeng ARM64 platform. Shared background,
conventions, and reference commands live in `references/kernel-context.md`
(relative to `${CLAUDE_SKILL_DIR}`). Read it before running any sub-skill.

## Input

`$ARGUMENTS` or the conversation context provides the task. If `$ARGUMENTS` is
empty, infer the intent from the conversation.

## Procedure

### 1. Read shared context

Read `${CLAUDE_SKILL_DIR}/references/kernel-context.md` to load the jinze kernel
conventions (branches, packaging layout, provenance/DCO rules, config files).

### 2. Select the sub-skill

Match the request to one sub-skill from the Sub-skill Map below. If the intent
is ambiguous or matches none, stop and ask the user which sub-skill to run
(list the available ones by title).

### 3. Run the sub-skill

Read the selected sub-skill's `SKILL.md` (path in the map) and follow it
exactly. Each sub-skill is self-contained and states its own inputs, procedure,
and output format.

## Sub-skill Map

Each entry maps an intent to a sub-skill directory (under
`${CLAUDE_SKILL_DIR}/subskills/`).

### evaluate-patchlist

- dir: `subskills/evaluate-patchlist`
- use when: the user provides a list of patches (a file, a mailing-list series,
  a set of commit SHAs, or `.patch`/`.mbox` files) and wants each patch assessed
  for relevance, correctness, risk, and applicability to the jinze kernel.
- keywords: patchlist, patch list, evaluate patches, patch series, backport
  assessment, "should we take these patches".

### review-merge-request

- dir: `subskills/review-merge-request`
- use when: the user wants a customer's merge request / MR / proposed branch /
  pull request reviewed for inclusion in the jinze kernel.
- keywords: merge request, MR, review branch, customer submission, review PR,
  "review this branch for jinze".

## Extending this skill

To add a sub-skill:

1. Create `subskills/<new-subskill>/SKILL.md` with its own front matter,
   `## Input`, `## Procedure`, and `## Output` sections. Reuse shared rules by
   referencing `../../references/kernel-context.md` instead of duplicating them.
2. Add a matching entry (dir, "use when", keywords) to the Sub-skill Map above.
3. Keep each sub-skill self-contained so it can run standalone.

Do not change the dispatcher logic in steps 1-3 when adding a sub-skill; only
the Sub-skill Map grows.
