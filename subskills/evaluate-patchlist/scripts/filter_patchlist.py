#!/usr/bin/env python3
"""
filter_patchlist.py - classify a jinze patchlist spreadsheet.

Implements the two classification steps of the evaluate-patchlist sub-skill:

  --stage kernel    : keep only kernel-space items (column C in {内核态, kernel}),
                      dropping userspace rows (qemu, rasdaemon, libvirt, 用户态).
  --stage upstream  : from the kernel items, keep only those targeting the
                      upstream Linux kernel, using column H (合入XX社区版本) and
                      cross-checking column L (社区类型). openEuler-OLK-only rows
                      are excluded and counted separately.

The classifier matches columns by their Chinese header text, so it tolerates
column reordering. It is read-only (only reads the .xlsx and writes the
requested output files).

Outputs:
  --out CSV       : filtered rows (all original columns).
  --commits FILE  : plain list of commit ids (one per line) for the kept rows.
Counts and any anomaly flags are printed to stderr.
"""

import argparse
import csv
import re
import sys
from collections import Counter

try:
    import openpyxl
except ImportError:
    sys.exit("error: openpyxl is required (pip install openpyxl)")

KERNEL_CATEGORIES = {"内核态", "kernel"}

# header -> internal key. Match by substring to tolerate minor wording changes.
HEADER_KEYS = {
    "category": ["分类"],
    "version": ["合入", "社区版本"],       # 合入XX社区版本
    "commit_id": ["commit id", "commit id"],
    "subject": ["commit信息", "标题描述"],
    "link": ["社区链接"],
    "ctype": ["社区类型"],
}


def find_columns(header):
    """Return {key: index} by matching header cell text."""
    norm = [(str(h).strip().lower() if h is not None else "") for h in header]
    idx = {}
    for key, needles in HEADER_KEYS.items():
        for i, h in enumerate(norm):
            if any(n.lower() in h for n in needles):
                idx[key] = i
                break
    return idx


def load_sheet(path, sheet):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        sys.exit("error: empty sheet")
    header = [("" if c is None else str(c)) for c in rows[0]]
    data = [r for r in rows[1:] if any(c is not None for c in r)]
    return header, data, ws.title


def cell(row, i):
    return (str(row[i]).strip() if i is not None and i < len(row) and row[i] is not None else "")


def is_upstream(hval, lval):
    """Classify a kernel row as upstream / euler / unknown from H and L."""
    h = hval.lower()
    l = lval
    h_euler = ("olk" in h) or ("openeuler" in h) or bool(re.search(r"6\.6\.0-", h))
    h_upstream = bool(re.search(r"v?\d+\.\d+", h)) and not h_euler
    l_euler = ("openEuler" in l) or ("olk" in l.lower())
    l_upstream = l.startswith("合入上游")
    # decide, and report disagreement
    if h_upstream and (l_upstream or not l):
        return "upstream", False
    if h_euler and (l_euler or not l):
        return "euler", False
    # H and L disagree, or H unknown
    if l_upstream and not h_euler:
        return "upstream", True
    if l_euler and not h_upstream:
        return "euler", True
    return "unknown", True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", help="patchlist .xlsx")
    ap.add_argument("--sheet", help="worksheet name (default: first)")
    ap.add_argument("--stage", choices=["kernel", "upstream"], required=True)
    ap.add_argument("--out", help="write filtered rows to this CSV")
    ap.add_argument("--commits", help="write kept commit ids to this file")
    args = ap.parse_args()

    header, data, title = load_sheet(args.xlsx, args.sheet)
    col = find_columns(header)
    for req in ("category", "commit_id"):
        if req not in col:
            sys.exit(f"error: could not locate '{req}' column in header: {header}")

    print(f"sheet: {title} | rows: {len(data)}", file=sys.stderr)
    cats = Counter(cell(r, col["category"]) for r in data)
    print("categories (col C): " + ", ".join(f"{k or '(blank)'}={v}" for k, v in cats.most_common()), file=sys.stderr)

    kernel = [r for r in data if cell(r, col["category"]) in KERNEL_CATEGORIES]
    print(f"kernel items (内核态/kernel): {len(kernel)}", file=sys.stderr)

    if args.stage == "kernel":
        kept = kernel
    else:  # upstream
        if "version" not in col or "ctype" not in col:
            print("warning: version(H)/ctype(L) column missing; classifying on whatever is present", file=sys.stderr)
        kept, euler, unknown, flagged = [], [], [], []
        for r in kernel:
            hv = cell(r, col.get("version"))
            lv = cell(r, col.get("ctype"))
            klass, disagree = is_upstream(hv, lv)
            if disagree:
                flagged.append((cell(r, col["commit_id"]), hv, lv, klass))
            if klass == "upstream":
                kept.append(r)
            elif klass == "euler":
                euler.append(r)
            else:
                unknown.append(r)
        print(f"upstream: {len(kept)} | openEuler-only: {len(euler)} | unknown: {len(unknown)}", file=sys.stderr)
        if flagged:
            print(f"H/L disagreements or unknowns ({len(flagged)}):", file=sys.stderr)
            for cid, hv, lv, k in flagged[:20]:
                print(f"  {cid[:14]:14s} H={hv!r} L={lv!r} -> {k}", file=sys.stderr)

    # commit-id sanity: flag malformed lengths
    cids = [cell(r, col["commit_id"]) for r in kept if cell(r, col["commit_id"])]
    bad = [c for c in cids if not re.fullmatch(r"[0-9a-fA-F]{12}|[0-9a-fA-F]{40}", c)]
    lens = Counter(len(c) for c in cids)
    print(f"commit ids: {len(cids)} (unique {len(set(cids))}) lengths={dict(lens)}", file=sys.stderr)
    if bad:
        print(f"malformed commit ids ({len(bad)}): " + ", ".join(repr(b) for b in bad[:10]), file=sys.stderr)

    if args.out:
        with open(args.out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            for r in kept:
                w.writerow([("" if c is None else str(c)) for c in r])
        print(f"wrote {args.out} ({len(kept)} rows)", file=sys.stderr)

    if args.commits:
        with open(args.commits, "w") as fh:
            fh.write("\n".join(cids) + ("\n" if cids else ""))
        print(f"wrote {args.commits} ({len(cids)} ids)", file=sys.stderr)

    if not args.out and not args.commits:
        # default: print commit ids to stdout
        print("\n".join(cids))


if __name__ == "__main__":
    main()
