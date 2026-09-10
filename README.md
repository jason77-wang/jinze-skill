# jinze skill

Assistant skill for the **jinze** team's `linux-kunpeng` kernel (Ubuntu Kunpeng,
Huawei Kunpeng ARM64, based on Noble / 6.8).

It is an umbrella skill that dispatches to focused **sub-skills** and shares a
common kernel-context reference. Two sub-skills ship today; more can be added
without touching the dispatcher.

## Layout

```
jinze/
├── SKILL.md                       # dispatcher: loads context, routes to a sub-skill
├── README.md                      # this file
├── references/
│   └── kernel-context.md          # shared conventions, reference repos, risk lenses
└── subskills/
    ├── evaluate-patchlist/        # sub-skill 1: assess a provided patchlist
    │   ├── SKILL.md
    │   └── scripts/
    │       ├── run_all.sh         # chain the mechanical steps (1-4)
    │       ├── filter_patchlist.py# steps 1-2: classify kernel / upstream items
    │       ├── port_difficulty.py # steps 3-4: group by feature + porting triage
    │       └── eval_patchlist.py  # steps 5-7: mechanical per-patch facts
    └── review-merge-request/      # sub-skill 2: review a customer MR / branch
        └── SKILL.md
```

## Reference repos (read-only)

Configured in `references/kernel-context.md`; used for provenance and precedent:

- **jinze kernel** (the working tree you run in): Ubuntu `linux-kunpeng`,
  integration branch `master-next`.
- **mainline**: `/home/hwang4/work/mainline/linux` — authoritative upstream
  origin for backport provenance.
- **openEuler**: `/home/hwang4/test/jinze/euler/linux-euler` (branch `OLK-6.6`)
  — Kunpeng/ARM64 precedent for out-of-tree behaviour.

Paths can be overridden per script via `--mainline` / `--euler`.

## How to trigger

Just ask in natural language; the parent `jinze` skill routes to the right
sub-skill by keyword.

- Evaluate a patchlist:
  > "Use the jinze skill to evaluate the patchlist `950_Beta_patchlist_20260814.xlsx`
  > against master-next."
- Review a merge request:
  > "Review this customer branch `<remote>/<branch>` for the jinze kernel."

To force the full walkthrough without a mid-way checkpoint, add: *"go through
all steps and don't stop to ask; write outputs to files."*

## Sub-skill 1: evaluate-patchlist

Assesses a delivered patchlist (commonly a jinze `.xlsx`) for inclusion.
Nine steps: (1) find kernel items, (2) find upstream commits, (3) group by
feature, (4) triage porting difficulty vs the target branch, (5) enumerate,
(6) establish base, (7) per-patch evaluation, (8) cross-check the series,
(9) recommend.

Steps 1-4 are mechanical and scripted. Run them in one shot:

```bash
bash subskills/evaluate-patchlist/scripts/run_all.sh \
    <patchlist.xlsx> <jinze-repo> [base]        # base defaults to master-next
```

Outputs (written to the current directory):

| file | contents |
|---|---|
| `kernel_items.csv` | rows where category (col C) is `内核态`/`kernel` |
| `upstream_items.csv` | kernel rows targeting the upstream Linux kernel (col H + L) |
| `upstream_commits.txt` | the upstream commit SHAs, one per line |
| `upstream_by_feature_difficulty.csv` | per-commit: feature, difficulty, reason, SHA, subject |
| `upstream_difficulty_summary.md` | feature x difficulty matrix |

Difficulty levels (apply-check of each upstream commit onto the target branch):
`present` < `easy` (clean) < `medium` (3-way) < `hard` (conflict/missing) <
`needs-fetch` (SHA absent from the local mainline clone; run
`git -C <mainline> fetch`).

Run scripts individually if you want just one stage:

```bash
# Step 1 only
python3 .../filter_patchlist.py <file.xlsx> --stage kernel --out kernel_items.csv
# Step 2 only
python3 .../filter_patchlist.py <file.xlsx> --stage upstream \
    --out upstream_items.csv --commits upstream_commits.txt
# Steps 3-4 only
python3 .../port_difficulty.py <file.xlsx> --repo <jinze-repo> --base master-next \
    --csv upstream_by_feature_difficulty.csv --md upstream_difficulty_summary.md
# Step 7 mechanical facts for a set of commits already in the jinze tree
python3 .../eval_patchlist.py --list upstream_commits.txt --repo <jinze-repo>
```

### Worked example

On `950_Beta_patchlist_20260814.xlsx` the pipeline classified 732 rows into
526 kernel items, of which **413 are upstream** and 113 openEuler-only, and
triaged the 413 by porting difficulty to `master-next` (6.8): 70 present,
74 easy, 190 medium, 69 hard, 10 needs-fetch. The heaviest feature is `k-smmu`
(133 commits); the hardest is `GE驱动`/hibmcge (40/47 hard).

> Note: the spreadsheet column letters/headers can change if the source file is
> restructured. The scripts match columns by **header text**, not position, and
> the sub-skill instructs the agent to confirm the header row and category
> values against the actual file before trusting the classification.

## Sub-skill 2: review-merge-request

Reviews a customer's merge request / branch / PR for the jinze kernel:
resolves the `base..head` range, does per-commit review (message hygiene, DCO,
provenance verified against mainline, atomicity, correctness) and whole-MR
review (scope, ABI, config, security, build/test), then gives a merge verdict.
Read-only; asks before posting any review.

## Extending

Add a sub-skill by creating `subskills/<name>/SKILL.md` (with its own front
matter, Input, Procedure, Output) and adding an entry to the **Sub-skill Map**
in the top-level `SKILL.md`. Reuse shared rules by referencing
`references/kernel-context.md` instead of duplicating them. The dispatcher logic
does not change — only the map grows.

## Safety

All tooling is read-only with respect to the jinze repo and the reference repos:
apply-checks run in throwaway detached worktrees that are removed afterwards, and
no script fetches or commits. Sub-skills ask before creating scratch branches or
posting reviews.
