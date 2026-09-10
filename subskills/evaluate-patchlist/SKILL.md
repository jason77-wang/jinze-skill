---
name: jinze-evaluate-patchlist
description: >
  Evaluate a provided patchlist for the jinze linux-kunpeng kernel. Assesses
  each patch for relevance to Kunpeng/ARM64, correctness, risk, provenance, and
  whether it applies cleanly, then gives an accept / rework / reject
  recommendation. Sub-skill of the jinze skill.
---

# jinze: evaluate patchlist

Assess a list of patches for inclusion in the jinze `linux-kunpeng` kernel.

Read `../../references/kernel-context.md` first for kernel conventions and the
risk lenses used below.

## Invocation

Trigger this sub-skill (via the parent `jinze` skill) with any request that
names a patchlist to evaluate, e.g.:

- "Use the jinze skill to evaluate the patchlist `<file.xlsx>` against
  `master-next`."
- "Run the jinze evaluate-patchlist sub-skill end-to-end on `<file.xlsx>`."

To run the whole pipeline without stopping for confirmation, say so explicitly
and ask for files, e.g.:

> Evaluate this patchlist for jinze and go through all steps: filter kernel
> items, filter upstream commits, group by feature, triage porting difficulty
> vs master-next, then per-patch evaluation, cross-check, and final
> recommendation. Write the outputs to files and don't stop to ask.

Behaviour notes:

- Steps 1-4 are mechanical and fast (classification, feature grouping, porting
  difficulty). The `run_all.sh` wrapper runs them in one shot (see below).
- Steps 5-9 are the per-patch correctness review and can be heavy for large
  lists (hundreds of commits). Unless the user says "all steps / don't stop to
  ask", pause after step 4 to confirm scope (e.g. which features to review in
  depth) before grinding through every commit.

Quick start for steps 1-4:

```
bash ${CLAUDE_SKILL_DIR}/subskills/evaluate-patchlist/scripts/run_all.sh \
    <patchlist.xlsx> <jinze-repo> [base]   # base defaults to master-next
```

It writes (into the current directory): `kernel_items.csv`,
`upstream_items.csv`, `upstream_commits.txt`,
`upstream_by_feature_difficulty.csv`, and `upstream_difficulty_summary.md`,
then prints where to continue (step 5).

## Input

`$ARGUMENTS` or the conversation provides the patchlist in one of these forms:

- A path to a file listing patches (one per line: URL, SHA, or `.patch` path).
- One or more `.patch` / `.mbox` files, or a mailing-list series URL.
- A set of commit SHAs (in this repo or an upstream reference).
- A **jinze patchlist spreadsheet** (`.xlsx`), the common jinze delivery format.
  Columns (Chinese headers): C `分类` (category: `内核态`/`kernel`/`qemu`/... ),
  H `合入XX社区版本` (target community version, e.g. `kernel v6.15-rc1` or
  `olk-6.6.0-...`), I `commit id`, J `commit信息` (subject), K `社区链接` (LKML
  link), L `社区类型` (`合入上游linux内核社区` vs `合入openEuler olk内核社区`).
- A target branch/base to evaluate against (default: current `master-next`, or
  ask if unclear).

If the patchlist location is ambiguous, stop and ask the user for it.

> Note: the column letters and header/value strings above describe the current
> jinze delivery format and **can change** if the source spreadsheet is
> restructured (columns reordered/renamed, or the category/community-version
> wording changed). The helper scripts match columns by header text (not fixed
> position) to tolerate reordering, but before trusting the classification always
> confirm against the actual file: print the header row and the distinct values
> of the category column (C) and the version/type columns (H, L). If a header or
> value no longer matches, adjust the mapping (scripts take `--sheet`; the
> matching rules live in `HEADER_KEYS` / `KERNEL_CATEGORIES` / `is_upstream`) or
> ask the user how the new columns map, rather than assuming fixed positions.

## Procedure

### 1. Classify: find the kernel items

If the patchlist is a spreadsheet (or otherwise mixes kernel and userspace
entries), first select only the kernel-space items. Use column C (`分类`):
keep rows whose category is `内核态` or `kernel`; drop userspace rows (`qemu`,
`rasdaemon`, `libvirt`, `用户态`, ...).

Run the helper to do this reproducibly:

```
python3 ${CLAUDE_SKILL_DIR}/subskills/evaluate-patchlist/scripts/filter_patchlist.py \
    <patchlist.xlsx> --stage kernel --out kernel_items.csv
```

Report the counts per category and how many kernel items remain.

### 2. Classify: find the upstream kernel commits

From the kernel items, select the ones whose target is the **upstream** Linux
kernel (these have real upstream SHAs to verify). Classify with column H
(`合入XX社区版本`) and cross-check column L (`社区类型`):

- upstream: H matches `kernel v?<X.Y>` (e.g. `kernel v6.15-rc1`, `kernel 6.8`)
  and L is `合入上游linux内核社区...`.
- openEuler-only: H is `olk-6.6.0-...` / `OLK 6.6.0-...` or L is
  `合入openEuler olk内核社区...`. These are **not** in mainline; verify them
  against the openEuler reference repo instead, and note that in the report.

If columns H and L disagree for a row, flag it rather than guessing. Run:

```
python3 ${CLAUDE_SKILL_DIR}/subskills/evaluate-patchlist/scripts/filter_patchlist.py \
    <patchlist.xlsx> --stage upstream \
    --out upstream_items.csv --commits upstream_commits.txt
```

Report: total kernel items, upstream count, openEuler-only count, and any
disagreement/typo flags (e.g. malformed commit ids). The upstream commit list
feeds the mechanical evaluator in the later steps.

### 3. Group by feature

Sort the upstream items by feature so the series is reviewed as coherent
feature groups rather than 400+ loose commits. Use spreadsheet column
`架构元素` (component/feature area, e.g. `k-smmu`, `GE驱动`, `k-cpufreq`),
falling back to `版本模块` (`Virtualization`, `Perf`, ...). Report the count per
feature. This grouping is produced automatically by the difficulty triage in the
next step.

### 4. Triage porting difficulty (per feature)

For each upstream commit, estimate how hard it is to port onto the target branch
(default `master-next`, currently 6.8). Fetch the commit's diff from the mainline
reference repo and apply-check it against a throwaway worktree of the base:

```
python3 ${CLAUDE_SKILL_DIR}/subskills/evaluate-patchlist/scripts/port_difficulty.py \
    <patchlist.xlsx> --repo <jinze-repo> --base master-next \
    --csv upstream_by_feature_difficulty.csv \
    --md  upstream_difficulty_summary.md
```

Difficulty levels:

- `present` - the commit's subject is already in the target branch history.
- `easy` - the diff applies cleanly (`git apply --check`).
- `medium` - applies via 3-way (`git apply --check --3way`).
- `hard` - does not apply (conflicts or missing files); see the reason column.
- `needs-fetch` - the SHA is absent from the local mainline clone; run
  `git -C /home/hwang4/work/mainline/linux fetch` and re-run.
- `error` - the diff could not be produced (e.g. a merge commit).

Output a feature x difficulty matrix (the `--md` file) and a per-commit CSV
(the `--csv` file). Use it to plan the port: schedule `present`/`easy` features
first, budget effort for `hard`-heavy features, and resolve `needs-fetch` before
final judgment. The triage is a fast mechanical signal; the per-patch
correctness review in later steps still governs the final verdict.

### 5. Enumerate the patches

Build an ordered list of patches. For each, capture: subject, author,
upstream/origin SHA if any, and the files it touches (from the diffstat).

### 6. Establish the base

Determine the base the patches target (a branch, tag, or SHA). Confirm the
current kernel version from `debian.kunpeng/changelog`.

### 7. Evaluate each patch

For every patch, assess and record:

- Relevance: is it needed for Kunpeng/ARM64, or a generic fix that matters
  here? Note the subsystem (from `MAINTAINERS`/paths). For Kunpeng-specific
  code, check the openEuler reference repo for an equivalent patch or precedent
  (`git -C /home/hwang4/test/jinze/euler/linux-euler log --oneline --grep ...`).
- Applicability: does it apply to the base? Run `git apply --check` (or a
  scratch-branch `git am` dry run). Record clean / needs-rebase / conflicts.
- Correctness: read the diff. Look for logic errors, missing error handling,
  locking issues, and whether it is complete (no dangling references to other
  unlisted patches).
- Dependencies: does it depend on earlier patches in the list or on commits not
  present? Flag ordering requirements.
- Provenance & DCO: is there a `Signed-off-by` chain and an upstream reference
  (`cherry picked from` / `backported from`)? Flag missing provenance. When an
  upstream SHA is cited, verify it against the local mainline reference repo
  (`git -C /home/hwang4/work/mainline/linux show <sha>`) and diff the backport
  against the upstream original to catch dropped hunks or unresolved conflicts.
- Risk lenses: apply Scope, ABI, Config, Security from the shared reference.
- Config/ABI impact: if it adds/changes Kconfig, note that
  `debian.kunpeng/config` must be updated.

### 8. Cross-check the series

- Detect duplicates, superseded patches, and conflicting hunks between patches.
- Verify the order applies cleanly as a whole.
- Note any patch that should be split, squashed, or dropped.

### 9. Recommend

Give each patch one verdict: `accept`, `accept-with-changes`, `rework`, or
`reject`, with a one-line reason. Then give an overall recommendation for the
series.

## Output

Produce a Markdown report:

1. Header: base/version evaluated, number of patches, date.
2. A summary table: `# | subject | subsystem | applies | risk | verdict`.
3. Per-patch detail: findings for each lens, with file:line references.
4. Series-level notes: ordering, duplicates, dependencies, missing prerequisites.
5. Overall recommendation and any required follow-ups (config updates, tests).

Cite exact file paths and line numbers. Do not modify the repository or apply
patches beyond dry-run `--check`; ask before creating scratch branches.
