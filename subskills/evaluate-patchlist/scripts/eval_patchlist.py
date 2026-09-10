#!/usr/bin/env python3
"""
eval_patchlist.py - mechanical evaluation helper for the jinze
evaluate-patchlist sub-skill.

It gathers the *facts* about a patchlist so the agent can focus on the
qualitative correctness/risk judgment. It is strictly read-only with respect to
the jinze repo checkout (apply-checks run in a throwaway detached worktree) and
the reference repos.

For each patch it collects:
  - subject, author, Signed-off-by presence
  - diffstat (files changed, insertions, deletions)
  - touched subsystems (top-level path guess) and config/ABI flags
  - upstream provenance SHA parsed from the commit message
  - whether that SHA exists in the mainline reference repo (+ first release)
  - openEuler precedent (commits whose subject matches), best-effort
  - apply-check result against the base (for .patch/.mbox inputs)

Inputs (any mix):
  positional PATHS   : .patch / .mbox files, or directories of them
  --list FILE        : a text file, one entry per line (path or SHA)
  --sha SHA          : a commit already present in the jinze repo (repeatable)

Output:
  Markdown report to stdout (default) or --out FILE, plus optional --json FILE.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict

DEFAULT_MAINLINE = "/home/hwang4/work/mainline/linux"
DEFAULT_EULER = "/home/hwang4/test/jinze/euler/linux-euler"
DEFAULT_BASE_CANDIDATES = ["master-next", "master", "HEAD"]

PROVENANCE_RES = [
    re.compile(r"cherry[\s-]*picked from commit\s+([0-9a-f]{7,40})", re.I),
    re.compile(r"backported from commit\s+([0-9a-f]{7,40})", re.I),
    re.compile(r"commit\s+([0-9a-f]{12,40})\s+upstream", re.I),
    re.compile(r"\[\s*upstream commit\s+([0-9a-f]{7,40})\s*\]", re.I),
]

SUBSYSTEM_HINTS = {
    "arch/arm64": "arm64",
    "drivers/scsi": "scsi",
    "drivers/net": "net",
    "drivers/pci": "pci",
    "drivers/acpi": "acpi",
    "drivers/iommu": "iommu",
    "drivers/perf": "perf",
    "drivers/crypto": "crypto",
    "mm/": "mm",
    "kernel/": "kernel-core",
    "fs/": "fs",
    "debian.kunpeng": "packaging",
}


def run(cmd, cwd=None, check=False):
    """Run a command, return (rc, stdout, stderr). Never raises on non-zero."""
    try:
        p = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=120
        )
        if check and p.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} -> {p.stderr.strip()}")
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout: {' '.join(cmd)}"


def repo_ok(path):
    if not path or not os.path.isdir(path):
        return False
    rc, _, _ = run(["git", "-C", path, "rev-parse", "--git-dir"])
    return rc == 0


def resolve_base(repo, requested):
    if requested:
        rc, out, _ = run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", requested + "^{commit}"])
        if rc == 0:
            return requested, out.strip()
        return requested, None  # requested but unresolved; caller warns
    for cand in DEFAULT_BASE_CANDIDATES:
        rc, out, _ = run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", cand + "^{commit}"])
        if rc == 0:
            return cand, out.strip()
    return None, None


@dataclass
class Patch:
    source: str
    kind: str  # "file" or "sha"
    subject: str = ""
    author: str = ""
    signed_off: bool = False
    files: list = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    subsystems: list = field(default_factory=list)
    touches_config: bool = False
    touches_kconfig: bool = False
    provenance_sha: str = ""
    mainline_status: str = "n/a"      # found / missing / no-provenance / no-repo
    mainline_release: str = ""
    euler_matches: list = field(default_factory=list)
    apply_status: str = "n/a"         # clean / conflicts / error / already-in-repo
    apply_detail: str = ""
    notes: list = field(default_factory=list)


def parse_message_and_stat(text):
    """From a raw patch/mbox text, extract subject, author, sob, provenance."""
    subject, author = "", ""
    signed_off = False
    prov = ""
    for line in text.splitlines():
        if not subject and line.startswith("Subject:"):
            subject = re.sub(r"^Subject:\s*(\[[^\]]*\]\s*)*", "", line).strip()
        if not author and line.startswith("From:"):
            author = line[len("From:"):].strip()
        if line.startswith("Signed-off-by:"):
            signed_off = True
    for rx in PROVENANCE_RES:
        m = rx.search(text)
        if m:
            prov = m.group(1)
            break
    return subject, author, signed_off, prov


def diffstat_from_patch(path):
    """Parse a unified diff for touched files and +/- counts."""
    files, ins, dele = [], 0, 0
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                if line.startswith("+++ b/"):
                    files.append(line[6:].strip())
                elif line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
                    files.append(line[4:].strip())
                elif line.startswith("+") and not line.startswith("+++"):
                    ins += 1
                elif line.startswith("-") and not line.startswith("---"):
                    dele += 1
    except OSError:
        pass
    # de-dup preserving order
    seen, uniq = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq, ins, dele


def subsystems_for(files):
    subs = []
    for f in files:
        for prefix, name in SUBSYSTEM_HINTS.items():
            if f.startswith(prefix) and name not in subs:
                subs.append(name)
    if not subs and files:
        subs.append(files[0].split("/")[0] or "?")
    return subs


def config_flags(files):
    cfg = any("debian.kunpeng/config" in f or f.startswith("debian") for f in files)
    kconfig = any(os.path.basename(f).startswith("Kconfig") or f.endswith("Kconfig") for f in files)
    return cfg, kconfig


def check_mainline(sha, mainline):
    if not sha:
        return "no-provenance", ""
    if not repo_ok(mainline):
        return "no-repo", ""
    rc, _, _ = run(["git", "-C", mainline, "cat-file", "-t", sha])
    if rc != 0:
        return "missing", ""
    rc, out, _ = run(["git", "-C", mainline, "describe", "--contains", "--match", "v*", sha])
    rel = out.strip().split("~")[0] if rc == 0 else ""
    return "found", rel


def check_euler(subject, euler, branch="OLK-6.6", limit=3):
    if not subject or not repo_ok(euler):
        return []
    # strip common prefixes / trailing noise, take a distinctive slice
    q = re.sub(r"^\[[^\]]*\]\s*", "", subject).strip()
    q = q[:60]
    rc, out, _ = run([
        "git", "-C", euler, "log", "--oneline", "--no-merges",
        f"-{limit}", f"--grep={re.escape(q)}", "-i", branch,
    ])
    if rc != 0 or not out.strip():
        return []
    return [ln.strip() for ln in out.strip().splitlines()][:limit]


def apply_check(repo, base_sha, patch_path):
    """Apply-check in a throwaway detached worktree so the user's tree is untouched."""
    if not base_sha:
        return "error", "base unresolved"
    tmp = tempfile.mkdtemp(prefix="jinze-applycheck-")
    wt = os.path.join(tmp, "wt")
    try:
        rc, _, err = run(["git", "-C", repo, "worktree", "add", "--detach", "--quiet", wt, base_sha])
        if rc != 0:
            return "error", f"worktree add failed: {err.strip()}"
        rc, out, err = run(["git", "-C", wt, "apply", "--check", "-p1", patch_path])
        if rc == 0:
            return "clean", ""
        # try -3way to see if it is a resolvable conflict vs. total miss
        rc3, _, err3 = run(["git", "-C", wt, "apply", "--check", "--3way", "-p1", patch_path])
        detail = (err or err3).strip().splitlines()
        detail = detail[0] if detail else "does not apply"
        return ("conflicts" if rc3 == 0 else "conflicts"), detail
    finally:
        run(["git", "-C", repo, "worktree", "remove", "--force", wt])
        try:
            os.rmdir(tmp)
        except OSError:
            pass


def load_sha(repo, sha, mainline, euler):
    p = Patch(source=sha, kind="sha")
    rc, out, _ = run(["git", "-C", repo, "show", "--no-patch",
                      "--format=%s%n%an <%ae>%n%b", sha])
    if rc != 0:
        p.notes.append("SHA not found in jinze repo")
        return p
    lines = out.splitlines()
    p.subject = lines[0] if lines else ""
    p.author = lines[1] if len(lines) > 1 else ""
    body = "\n".join(lines[2:])
    p.signed_off = "Signed-off-by:" in out
    for rx in PROVENANCE_RES:
        m = rx.search(out)
        if m:
            p.provenance_sha = m.group(1)
            break
    rc, stat, _ = run(["git", "-C", repo, "show", "--numstat", "--format=", sha])
    for ln in stat.splitlines():
        parts = ln.split("\t")
        if len(parts) == 3:
            a, d, fn = parts
            p.files.append(fn)
            p.insertions += int(a) if a.isdigit() else 0
            p.deletions += int(d) if d.isdigit() else 0
    p.subsystems = subsystems_for(p.files)
    p.touches_config, p.touches_kconfig = config_flags(p.files)
    p.mainline_status, p.mainline_release = check_mainline(p.provenance_sha, mainline)
    p.euler_matches = check_euler(p.subject, euler)
    p.apply_status = "already-in-repo"
    return p


def load_file(repo, base_sha, path, mainline, euler):
    p = Patch(source=path, kind="file")
    try:
        with open(path, "r", errors="replace") as fh:
            text = fh.read()
    except OSError as e:
        p.notes.append(f"cannot read: {e}")
        return p
    p.subject, p.author, p.signed_off, p.provenance_sha = parse_message_and_stat(text)
    p.files, p.insertions, p.deletions = diffstat_from_patch(path)
    p.subsystems = subsystems_for(p.files)
    p.touches_config, p.touches_kconfig = config_flags(p.files)
    p.mainline_status, p.mainline_release = check_mainline(p.provenance_sha, mainline)
    p.euler_matches = check_euler(p.subject, euler)
    p.apply_status, p.apply_detail = apply_check(repo, base_sha, path)
    if not p.signed_off:
        p.notes.append("no Signed-off-by")
    if not p.provenance_sha:
        p.notes.append("no upstream provenance cited")
    return p


def gather_sources(paths, list_file, shas):
    files, sha_list = [], list(shas or [])
    for pth in paths or []:
        if os.path.isdir(pth):
            for name in sorted(os.listdir(pth)):
                if name.endswith((".patch", ".mbox", ".eml")):
                    files.append(os.path.join(pth, name))
        elif os.path.isfile(pth):
            files.append(pth)
        elif re.fullmatch(r"[0-9a-f]{7,40}", pth):
            sha_list.append(pth)
    if list_file:
        with open(list_file) as fh:
            for ln in fh:
                e = ln.strip()
                if not e or e.startswith("#"):
                    continue
                if os.path.isfile(e):
                    files.append(e)
                elif re.fullmatch(r"[0-9a-f]{7,40}", e):
                    sha_list.append(e)
                else:
                    # unknown token (e.g. URL) - record for the agent to fetch
                    files.append(e)
    return files, sha_list


def md_table(patches):
    rows = ["| # | subject | subsystem | applies | prov→mainline | euler | flags |",
            "|---|---------|-----------|---------|---------------|-------|-------|"]
    for i, p in enumerate(patches, 1):
        flags = []
        if p.touches_config:
            flags.append("config")
        if p.touches_kconfig:
            flags.append("Kconfig")
        if not p.signed_off:
            flags.append("no-SoB")
        subj = (p.subject or "(no subject)")[:48].replace("|", "\\|")
        mainline = p.mainline_status + (f" {p.mainline_release}" if p.mainline_release else "")
        euler = "yes" if p.euler_matches else "-"
        rows.append(
            f"| {i} | {subj} | {','.join(p.subsystems) or '?'} | "
            f"{p.apply_status} | {mainline} | {euler} | {','.join(flags) or '-'} |"
        )
    return "\n".join(rows)


def md_report(meta, patches):
    out = []
    out.append(f"# Patchlist evaluation (mechanical facts)\n")
    out.append(f"- jinze repo: `{meta['repo']}`")
    out.append(f"- base: `{meta['base']}`" + (f" (`{meta['base_sha'][:12]}`)" if meta['base_sha'] else " **(unresolved)**"))
    out.append(f"- kernel version: {meta['version']}")
    out.append(f"- mainline ref: `{meta['mainline']}` ({'ok' if meta['mainline_ok'] else 'MISSING'})")
    out.append(f"- openEuler ref: `{meta['euler']}` ({'ok' if meta['euler_ok'] else 'MISSING'})")
    out.append(f"- patches: {len(patches)}\n")
    out.append("## Summary\n")
    out.append(md_table(patches))
    out.append("\n## Per-patch facts\n")
    for i, p in enumerate(patches, 1):
        out.append(f"### {i}. {p.subject or '(no subject)'}")
        out.append(f"- source: `{p.source}` ({p.kind})")
        out.append(f"- author: {p.author or '?'} | Signed-off-by: {'yes' if p.signed_off else 'NO'}")
        out.append(f"- diffstat: {len(p.files)} files, +{p.insertions}/-{p.deletions}")
        if p.files:
            shown = ", ".join(f"`{f}`" for f in p.files[:12])
            more = "" if len(p.files) <= 12 else f" (+{len(p.files)-12} more)"
            out.append(f"- files: {shown}{more}")
        out.append(f"- subsystems: {', '.join(p.subsystems) or '?'}")
        out.append(f"- apply-check: {p.apply_status}" + (f" ({p.apply_detail})" if p.apply_detail else ""))
        prov = p.provenance_sha or "none"
        out.append(f"- provenance: {prov} -> mainline: {p.mainline_status}" +
                   (f", first release {p.mainline_release}" if p.mainline_release else ""))
        if p.euler_matches:
            out.append("- openEuler precedent:")
            for m in p.euler_matches:
                out.append(f"    - {m}")
        if p.notes:
            out.append(f"- flags: {'; '.join(p.notes)}")
        out.append("")
    out.append("## Next steps for the agent\n")
    out.append("- Read each diff for correctness (logic, error handling, locking, concurrency).")
    out.append("- For backports marked `found`, diff against upstream to confirm no dropped hunks.")
    out.append("- For `missing`/`no-provenance`, ask the customer for the upstream origin.")
    out.append("- For `conflicts`, determine whether a rebase resolves it.")
    out.append("- Resolve series ordering/duplicates, then assign per-patch verdicts.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help=".patch/.mbox files, directories, or SHAs")
    ap.add_argument("--list", dest="list_file", help="file listing patches (one per line)")
    ap.add_argument("--sha", action="append", default=[], help="commit SHA already in the jinze repo (repeatable)")
    ap.add_argument("--repo", default=os.getcwd(), help="jinze repo path (default: cwd)")
    ap.add_argument("--base", help="base ref to evaluate against (default: master-next/master/HEAD)")
    ap.add_argument("--mainline", default=DEFAULT_MAINLINE, help="mainline reference repo")
    ap.add_argument("--euler", default=DEFAULT_EULER, help="openEuler reference repo")
    ap.add_argument("--out", help="write markdown report to this file (default: stdout)")
    ap.add_argument("--json", dest="json_out", help="also write machine-readable JSON here")
    args = ap.parse_args()

    if not repo_ok(args.repo):
        sys.exit(f"error: --repo is not a git repo: {args.repo}")

    base_name, base_sha = resolve_base(args.repo, args.base)
    rc, ver, _ = run(["sed", "-n", "1p", os.path.join(args.repo, "debian.kunpeng/changelog")])
    version = ver.strip() if rc == 0 and ver.strip() else "unknown"

    files, shas = gather_sources(args.paths, args.list_file, args.sha)
    if not files and not shas:
        sys.exit("error: no patches given (provide files, --list, --sha, or SHAs)")

    patches = []
    for f in files:
        if os.path.isfile(f):
            patches.append(load_file(args.repo, base_sha, f, args.mainline, args.euler))
        else:
            p = Patch(source=f, kind="file")
            p.notes.append("not a local file (URL?) - fetch before evaluating")
            patches.append(p)
    for s in shas:
        patches.append(load_sha(args.repo, s, args.mainline, args.euler))

    meta = {
        "repo": args.repo,
        "base": base_name or "?",
        "base_sha": base_sha or "",
        "version": version,
        "mainline": args.mainline,
        "mainline_ok": repo_ok(args.mainline),
        "euler": args.euler,
        "euler_ok": repo_ok(args.euler),
    }

    report = md_report(meta, patches)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(report + "\n")
        print(f"wrote {args.out}")
    else:
        print(report)

    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump({"meta": meta, "patches": [asdict(p) for p in patches]}, fh, indent=2)
        print(f"wrote {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
