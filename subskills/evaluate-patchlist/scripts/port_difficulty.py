#!/usr/bin/env python3
"""
port_difficulty.py - triage a jinze patchlist by feature and by how hard each
upstream commit is to port onto a target branch.

For each upstream commit it:
  1. resolves the SHA in the mainline reference repo,
  2. fetches that commit's diff (git format-patch),
  3. apply-checks the diff against a throwaway worktree of the target branch,
and assigns a difficulty:

  present     - the commit's subject is already in the target branch history
  easy        - diff applies cleanly (git apply --check)
  medium      - diff applies via 3-way (git apply --check --3way)
  hard        - diff does not apply (conflicts or missing files)
  needs-fetch - SHA not present in the local mainline clone (run: git fetch)
  error       - could not produce the diff (e.g. merge commit)

Results are grouped by feature (spreadsheet column 架构元素, falling back to
版本模块) and sorted by feature size then difficulty. Read-only: the target repo
is touched only via a detached worktree that is removed at the end.

Inputs:
  patchlist.xlsx           the jinze delivery spreadsheet, OR
  --commits FILE           a plain list of SHAs (one per line; no feature grouping)

Outputs:
  --csv FILE   per-commit rows (feature, module, difficulty, reason, commit, subject)
  --md FILE    a feature x difficulty summary table
Counts print to stderr.
"""

import argparse
import collections
import csv
import os
import re
import subprocess
import sys
import tempfile

DEFAULT_MAINLINE = "/home/hwang4/work/mainline/linux"
DIFF_ORDER = {"present": 0, "easy": 1, "medium": 2, "hard": 3,
              "needs-fetch": 4, "error": 5}
KERNEL_CATEGORIES = {"内核态", "kernel"}


def run(cmd, cwd=None, inp=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       input=inp, timeout=180, errors="replace")
    return p.returncode, p.stdout, p.stderr


def norm_subject(s):
    s = re.sub(r"^\s*\[[^\]]*\]\s*", "", s)
    s = re.sub(r"^(UBUNTU:\s*(SAUCE:)?\s*)+", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip().lower()


def is_upstream(hval):
    h = hval.lower()
    if "olk" in h or "openeuler" in h or re.search(r"6\.6\.0-", h):
        return False
    return bool(re.search(r"v?\d+\.\d+", h))


def load_from_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    for cand in wb.worksheets:
        if "kernel" in cand.title.lower() or "内核" in cand.title:
            ws = cand
            break
    rows = list(ws.iter_rows(values_only=True))
    header = [("" if c is None else str(c)) for c in rows[0]]

    def col(*needles):
        for i, h in enumerate(header):
            if any(n in h for n in needles):
                return i
        return None
    ci = {
        "cat": col("分类"), "feat": col("架构元素"), "mod": col("版本模块"),
        "ver": col("合入", "社区版本"), "cid": col("commit id"),
        "subj": col("commit信息"), "desc": col("标题描述"),
    }
    out = []
    for r in rows[1:]:
        if not any(c is not None for c in r):
            continue

        def g(key):
            i = ci.get(key)
            return (str(r[i]).strip() if i is not None and i < len(r) and r[i] is not None else "")
        if g("cat") not in KERNEL_CATEGORIES:
            continue
        if not is_upstream(g("ver")):
            continue
        out.append({
            "feature": g("feat") or g("mod") or "?",
            "module": g("mod"), "commit": g("cid"),
            "subject": g("subj") or g("desc"), "version": g("ver"),
        })
    return out


def load_from_commits(path):
    out = []
    with open(path) as fh:
        for ln in fh:
            s = ln.strip()
            if s and not s.startswith("#"):
                out.append({"feature": "(ungrouped)", "module": "",
                            "commit": s, "subject": "", "version": ""})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="patchlist .xlsx (or use --commits)")
    ap.add_argument("--commits", help="plain SHA list instead of an xlsx")
    ap.add_argument("--repo", default=os.getcwd(), help="target jinze repo (default: cwd)")
    ap.add_argument("--base", default="master-next", help="target branch (default: master-next)")
    ap.add_argument("--mainline", default=DEFAULT_MAINLINE, help="mainline reference repo")
    ap.add_argument("--csv", help="write per-commit CSV here")
    ap.add_argument("--md", help="write feature x difficulty summary markdown here")
    args = ap.parse_args()

    items = load_from_commits(args.commits) if args.commits else load_from_xlsx(args.source)
    if not items:
        sys.exit("error: no upstream commits found")
    print(f"upstream commits: {len(items)}", file=sys.stderr)

    rc, base_sha, err = run(["git", "-C", args.repo, "rev-parse", args.base])
    if rc != 0:
        sys.exit(f"error: base {args.base} not found: {err.strip()}")
    base_sha = base_sha.strip()

    print("indexing target-branch subjects...", file=sys.stderr)
    _, subj_out, _ = run(["git", "-C", args.repo, "log", args.base, "--format=%s", "--no-merges"])
    base_subjects = {norm_subject(l) for l in subj_out.splitlines() if l.strip()}
    print(f"  {len(base_subjects)} subjects indexed", file=sys.stderr)

    tmp = tempfile.mkdtemp(prefix="jinze-port-")
    wt = os.path.join(tmp, "wt")
    rc, _, err = run(["git", "-C", args.repo, "worktree", "add", "--detach", "--quiet", wt, base_sha])
    if rc != 0:
        sys.exit(f"error: worktree add failed: {err.strip()}")

    def classify(sha, subject):
        rc, typ, _ = run(["git", "-C", args.mainline, "cat-file", "-t", sha])
        if typ.strip() != "commit":
            return "needs-fetch", "sha not in local mainline clone"
        rc, patch, e = run(["git", "-C", args.mainline, "format-patch", "-1", "--stdout", "--no-signature", sha])
        if rc != 0 or not patch:
            return "error", f"format-patch failed: {e.strip()[:50]}"
        if subject and norm_subject(subject) in base_subjects:
            return "present", "subject already in target branch"
        pf = os.path.join(tmp, "p.patch")
        with open(pf, "w") as fh:
            fh.write(patch)
        rc, _, e1 = run(["git", "-C", wt, "apply", "--check", "-p1", pf])
        if rc == 0:
            return "easy", "clean apply"
        rc3, _, e3 = run(["git", "-C", wt, "apply", "--check", "--3way", "-p1", pf])
        if rc3 == 0:
            return "medium", "applies via 3-way"
        reason = (e1 or e3).strip().splitlines()
        return "hard", (reason[0][:70] if reason else "does not apply")

    try:
        for i, it in enumerate(items, 1):
            it["difficulty"], it["reason"] = classify(it["commit"], it["subject"])
            if i % 50 == 0:
                print(f"  {i}/{len(items)}", file=sys.stderr)
    finally:
        run(["git", "-C", args.repo, "worktree", "remove", "--force", wt])
        try:
            os.rmdir(tmp)
        except OSError:
            pass

    featcount = collections.Counter(it["feature"] for it in items)
    items.sort(key=lambda x: (-featcount[x["feature"]], x["feature"],
                              DIFF_ORDER.get(x["difficulty"], 9), x["subject"]))

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["feature", "module", "difficulty", "reason", "commit", "subject", "version"])
            for x in items:
                w.writerow([x["feature"], x["module"], x["difficulty"], x["reason"],
                            x["commit"], x["subject"], x["version"]])
        print(f"wrote {args.csv}", file=sys.stderr)

    order = ["present", "easy", "medium", "hard", "needs-fetch", "error"]
    byF = collections.defaultdict(list)
    for x in items:
        byF[x["feature"]].append(x)
    md = ["# Upstream patches by feature x porting difficulty to " + args.base + "\n",
          f"Total {len(items)} upstream commits. Difficulty = apply-check of each "
          "upstream commit's diff onto a throwaway target-branch worktree.\n",
          "Scale: present < easy (clean) < medium (3-way) < hard (conflict/missing) "
          "< needs-fetch (absent from local mainline).\n",
          "| Feature | tot | present | easy | medium | hard | needs-fetch |",
          "|---|--:|--:|--:|--:|--:|--:|"]
    for feat, its in sorted(byF.items(), key=lambda kv: -len(kv[1])):
        c = collections.Counter(x["difficulty"] for x in its)
        md.append(f"| {feat} | {len(its)} | {c.get('present',0)} | {c.get('easy',0)} | "
                  f"{c.get('medium',0)} | {c.get('hard',0)} | {c.get('needs-fetch',0)+c.get('error',0)} |")
    t = collections.Counter(x["difficulty"] for x in items)
    md.append(f"| **TOTAL** | **{len(items)}** | **{t.get('present',0)}** | **{t.get('easy',0)}** | "
              f"**{t.get('medium',0)}** | **{t.get('hard',0)}** | **{t.get('needs-fetch',0)+t.get('error',0)}** |")
    text = "\n".join(md) + "\n"
    if args.md:
        with open(args.md, "w") as fh:
            fh.write(text)
        print(f"wrote {args.md}", file=sys.stderr)
    else:
        print(text)

    print("=== overall ===", file=sys.stderr)
    for k in order:
        if t.get(k):
            print(f"  {k:11s} {t[k]}", file=sys.stderr)


if __name__ == "__main__":
    main()
