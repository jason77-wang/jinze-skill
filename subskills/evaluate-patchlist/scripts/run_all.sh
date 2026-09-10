#!/usr/bin/env bash
#
# run_all.sh - chain the mechanical steps (1-4) of the jinze evaluate-patchlist
# sub-skill: classify kernel items, classify upstream commits, group by feature,
# and triage porting difficulty against the target branch.
#
# Usage:
#   run_all.sh <patchlist.xlsx> <jinze-repo> [base-branch]
#
#   base-branch defaults to master-next.
#
# All output files are written into the current working directory. The script is
# read-only with respect to both the jinze repo and the reference repos (the
# difficulty check uses a throwaway detached worktree that is removed afterwards).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -lt 2 ]; then
    echo "usage: $0 <patchlist.xlsx> <jinze-repo> [base-branch]" >&2
    exit 2
fi

XLSX="$1"
REPO="$2"
BASE="${3:-master-next}"

if [ ! -f "$XLSX" ]; then
    echo "error: patchlist not found: $XLSX" >&2
    exit 1
fi
if [ ! -d "$REPO/.git" ] && ! git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
    echo "error: not a git repo: $REPO" >&2
    exit 1
fi

echo "== Step 1: classify kernel items ==" >&2
python3 "$SCRIPT_DIR/filter_patchlist.py" "$XLSX" --stage kernel \
    --out kernel_items.csv

echo >&2
echo "== Step 2: classify upstream kernel commits ==" >&2
python3 "$SCRIPT_DIR/filter_patchlist.py" "$XLSX" --stage upstream \
    --out upstream_items.csv --commits upstream_commits.txt

echo >&2
echo "== Steps 3-4: group by feature + triage porting difficulty vs $BASE ==" >&2
python3 "$SCRIPT_DIR/port_difficulty.py" "$XLSX" \
    --repo "$REPO" --base "$BASE" \
    --csv upstream_by_feature_difficulty.csv \
    --md  upstream_difficulty_summary.md

echo >&2
echo "== Done (mechanical steps 1-4) ==" >&2
echo "Outputs in $(pwd):" >&2
for f in kernel_items.csv upstream_items.csv upstream_commits.txt \
         upstream_by_feature_difficulty.csv upstream_difficulty_summary.md; do
    [ -f "$f" ] && echo "  - $f" >&2
done
echo >&2
echo "Next: proceed to step 5 (enumerate) and step 7 (per-patch correctness" >&2
echo "review). Use eval_patchlist.py --list upstream_commits.txt for mechanical" >&2
echo "facts, and review the 'hard'/'needs-fetch' rows in the difficulty CSV first." >&2
