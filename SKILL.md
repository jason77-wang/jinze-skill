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

### 2. Verify reference repos (preflight)

Both sub-skills use two read-only reference clones for provenance and precedent
(paths from `references/kernel-context.md`, overridable via the environment
variables `JINZE_MAINLINE_REPO` and `JINZE_EULER_REPO`):

- **mainline**: `${JINZE_MAINLINE_REPO:-/home/hwang4/work/mainline/linux}`
- **openEuler**: `${JINZE_EULER_REPO:-/home/hwang4/test/jinze/euler/linux-euler}`

Check each path is a real git repo before routing:

```bash
for p in "${JINZE_MAINLINE_REPO:-/home/hwang4/work/mainline/linux}" \
         "${JINZE_EULER_REPO:-/home/hwang4/test/jinze/euler/linux-euler}"; do
  git -C "$p" rev-parse --git-dir >/dev/null 2>&1 && echo "OK   $p" || echo "MISSING $p"
done
```

If **both** are present, continue to step 3 silently.

If **either** is `MISSING`, do not fail. Notify the user which repo(s) are
missing and what the impact is (backport provenance / source-diffing for the
affected origin cannot be verified and those commits will be marked
**provenance-unverified**), then use the `ask_user` tool to let them choose how
to proceed:

- **Clone the missing repo(s) now** — then clone into the expected paths (or a
  path they give, which you then export as `JINZE_MAINLINE_REPO` /
  `JINZE_EULER_REPO`) and re-run the check:
  - mainline:  `git clone <git.kernel.org linux> <path>`
  - openEuler: `git clone https://atomgit.com/openeuler/kernel.git <path>`
    (default branch `OLK-6.6`)
- **Run without the repo(s)** — proceed with the review/evaluation, applying the
  fallback rules from `kernel-context.md` (mainline: try upstream URLs then note
  it; openEuler: note absence and continue) and clearly flag every commit whose
  source could not be verified.

Respect the user's choice; if they decline to answer, default to running without
the missing repo(s) and flag the unverified commits.

### 3. Select the sub-skill

Match the request to one sub-skill from the Sub-skill Map below. If the intent
is ambiguous or matches none, stop and ask the user which sub-skill to run
(list the available ones by title).

### 4. Run the sub-skill

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

Do not change the dispatcher logic in steps 1-4 when adding a sub-skill; only
the Sub-skill Map grows.
