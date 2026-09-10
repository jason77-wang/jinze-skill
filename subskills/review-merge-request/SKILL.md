---
name: jinze-review-merge-request
description: >
  Review a customer's merge request (branch / MR / pull request) for the jinze
  linux-kunpeng kernel. Checks each commit for Ubuntu/DCO conventions,
  correctness, Kunpeng/ARM64 scope, ABI and config impact, and build/test
  readiness, then gives a merge recommendation. Sub-skill of the jinze skill.
---

# jinze: review merge request

Review a customer-submitted merge request against the jinze `linux-kunpeng`
kernel and recommend whether to merge.

Read `../../references/kernel-context.md` first for kernel conventions and the
risk lenses used below.

## Input

`$ARGUMENTS` or the conversation provides:

- The MR source: a git remote+branch, a `<base>...<branch>` range, an MR/PR
  URL, or a set of commits.
- The target/base branch (default: `master-next`; confirm if unclear).

If the source or base is ambiguous, stop and ask the user.

## Procedure

### 0. Fetch and resolve the MR head

Make the head and base available locally without modifying any existing branch:

- Git remote+branch: `git fetch <remote> <branch>` then use `FETCH_HEAD` as the
  head (or a scratch ref `refs/mr/review`). Do not check it out over the user's
  working branch.
- `<base>...<branch>` range or explicit SHAs: use as given.
- GitHub PR URL: fetch metadata with the GitHub tools (`pull_request_read`) and
  the PR's head SHA/branch; fetch that ref.
- Ensure the base ref is current: `git fetch origin master-next` (or the
  confirmed base) so the count is measured against the latest base.

### 1. Resolve the range and count new patches

Determine base and head. The base defaults to `master-next` (confirm if
unclear).

First, tell the reviewer **how many new patches the MR adds relative to
`master-next`** — this is the single most important framing number. Count only
the commits unique to the MR head (exclude commits already in `master-next`):

```
git --no-pager rev-list --count master-next..<head>   # new-patch count
git --no-pager log --oneline master-next..<head>       # the new patches
```

Use `<base>` in place of `master-next` if the user confirmed a different base.
State this count up front (e.g. "This MR adds N new patches on top of
master-next") before any per-commit detail, and repeat it in the output header.

Then list the overall diffstat with
`git --no-pager diff --stat <base>...<head>`.

### 2. Per-commit review

For each commit (`git --no-pager show <sha>`), check:

- Message hygiene: clear subject; correct Ubuntu prefix where applicable
  (`UBUNTU:`, `UBUNTU: SAUCE:`, `[Config]`); body explains the why.
- DCO / provenance: `Signed-off-by` present and chain intact; upstream origin
  cited for backports (`cherry picked from` / `backported from`); `BugLink`/
  `Link` where a tracked issue exists. Every cited backport SHA must be verified
  and diffed against its source — do this in step 2a below (mainline SHAs against
  `/home/hwang4/work/mainline/linux`, openEuler/atomgit SHAs against
  `/home/hwang4/test/jinze/euler/linux-euler`).
- Atomicity: one logical change per commit; no unrelated churn; builds at each
  commit if the customer claims bisectability.
- Correctness: read the diff for logic errors, error handling, locking,
  concurrency, and use of user-supplied input.

### 2a. Compare every backported patch against its source (MANDATORY)

For **every** commit that cites an origin (`cherry picked from commit <sha>` /
`backported from commit <sha>`), you MUST diff the patch against that source
commit — never rely on the subject line or the presence of the SHA alone. Skip
this only for genuinely original commits (`UBUNTU: SAUCE:` with no cited
upstream), and say so explicitly.

1. Locate each source SHA in the right reference repo:
   - kernel.org / mainline SHA → `/home/hwang4/work/mainline/linux`
   - openEuler / atomgit SHA (`https://atomgit.com/openeuler/kernel.git`) →
     `/home/hwang4/test/jinze/euler/linux-euler`
   First confirm the SHA exists there:
   `git -C <refrepo> show -s --oneline <src-sha>`. If it is missing (repo
   absent or SHA not fetched), mark the commit **provenance-unverified** and
   flag it — do not assume it matches.

2. Diff the customer patch against the source patch (compare the *changes*, not
   the trees), ignoring index/hunk/context noise:
   ```
   diff \
     <(git -C <repo>    show <local-sha> --format="" -U0 | grep -vE '^index |^@@|^diff --git|^--- |^\+\+\+ ') \
     <(git -C <refrepo> show <src-sha>   --format="" -U0 | grep -vE '^index |^@@|^diff --git|^--- |^\+\+\+ ')
   ```
   To classify the whole series at once, loop this over every
   local-SHA→source-SHA pair and label each **IDENTICAL** or **DIFFERS**.

3. For every commit that **DIFFERS**, read the delta and classify it as one of:
   - **legitimate backport adaptation** — e.g. dropping openEuler `KABI_*`
     reserved-field macros, redirecting a `*_defconfig` change to
     `debian.kunpeng/config/annotations`, removing `#ifdef`s for
     openEuler-only features/fields the jinze kernel lacks (e.g.
     `CONFIG_QOS_SCHED_DYNAMIC_AFFINITY`, `p->select_cpus`), or resolving a
     context conflict. Confirm the adaptation is functionally equivalent and
     correct for the jinze tree.
   - **unexplained / suspect divergence** — logic changes, dropped hunks, or
     altered behaviour with no backport rationale → flag as a finding
     (blocking if it changes behaviour or drops a fix).
   Additionally, any DIFFERS commit whose message lacks a `Conflicts:` / backport
   note describing the adaptation is a provenance-hygiene nit — call it out and
   recommend adding the note.

4. Report the comparison outcome explicitly: state how many commits are
   IDENTICAL vs DIFFERS, and give a per-commit table for the DIFFERS set with
   the adaptation and your assessment (see Output). Never present a backport
   review without this source comparison having been run.

### 3. Whole-MR review

- Scope: changes stay within Kunpeng/ARM64-relevant areas, or generic-core
  changes are justified and low-regression-risk. For Kunpeng-specific changes,
  cross-check the openEuler reference repo
  (`/home/hwang4/test/jinze/euler/linux-euler`) for precedent or a divergent
  solution.
- ABI: any exported-symbol / module ABI change (Ubuntu tracks ABI); flag if the
  ABI files need bumping.
- Config: first determine whether the MR **introduces any new Kconfig
  symbol**. Scan the range diff for added `config`/`menuconfig` entries in any
  `Kconfig*` file:
  `git --no-pager diff <base>...<head> -- '*Kconfig*' | grep -E '^\+(config|menuconfig) '`
  Also list all touched Kconfig files:
  `git --no-pager diff --stat <base>...<head> -- '*Kconfig*'`.
  For every new symbol found, verify that:
    - it has a matching default in `debian.kunpeng/config` (grep the symbol,
      e.g. `grep -R "CONFIG_<SYMBOL>" debian.kunpeng/config`); a new symbol
      absent from the config annotations is a **blocking** issue because the
      Ubuntu build/ABI check will fail;
    - the change carries a `UBUNTU: [Config]` changelog entry in
      `debian.kunpeng/changelog`;
    - the symbol's `default`/`depends on` keep it disabled or ARM64-scoped so it
      does not silently enable code on other flavours.
  If the MR introduces **no** new Kconfig symbol, state that explicitly. Existing
  `Kconfig` edits (help text, deps) must still be mirrored in
  `debian.kunpeng/config` with a `[Config]` changelog entry.
- Security: introduces or fixes a vulnerability; note CVE if referenced.
- Build/test: does it build for arm64; is there a test, reproduction, or CI
  result? Note what testing is still required.

### 4. Recommend

Overall verdict: `approve`, `approve-with-nits`, `request-changes`, or
`reject`, with the top blocking items called out.

## Output

Produce a Markdown review:

1. Header: MR source, base branch, **number of new patches added vs
   master-next** (stated prominently), commit count, files changed.
2. Per-commit notes: keyed by short SHA + subject, with findings and
   file:line references.
3. Source comparison (for backports): the IDENTICAL-vs-DIFFERS count from step
   2a, plus a table for every DIFFERS commit (local SHA, source SHA, the
   divergence, and whether it is a legitimate adaptation or a suspect
   divergence). Mark any commit whose source could not be verified.
4. MR-level findings: grouped by lens (scope, ABI, config, security, build/test).
5. Blocking issues vs. nits, clearly separated.
6. Overall verdict and the concrete changes needed to reach `approve`.

If the user wants the review posted (e.g. as PR comments via the GitHub tools or
a Launchpad MR), ask before posting. Do not modify the repository or the MR
branch. Keep review comments specific and actionable; skip style nits already
enforced by tooling.
