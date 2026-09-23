# jinze kernel context

Shared background and conventions used by all jinze sub-skills. Sub-skills
reference this file instead of duplicating the rules.

## What the jinze kernel is

- Package: `linux-kunpeng`, an Ubuntu-derived kernel for the Huawei Kunpeng
  ARM64 (aarch64) platform.
- Base: Ubuntu Noble, kernel 6.8 (`Ubuntu-kunpeng-6.8.0-100x.y` tags).
- Primary remote: `origin` (`~jinze-team` on Launchpad). Integration branches
  are `master` and `master-next`; feature branches carry topic names.

## Mainline reference repo

A local upstream mainline Linux clone is available at:

- Path: `/home/hwang4/work/mainline/linux` (override with `JINZE_MAINLINE_REPO`)
- Remote: `linux-next` (git.kernel.org). Contains upstream tags/history.

Use it to verify provenance and backports without hitting the network:

- Confirm a cited SHA exists upstream and read the original commit:
  `git -C /home/hwang4/work/mainline/linux show <sha>`
- Compare a backport against the upstream original:
  `git -C /home/hwang4/work/mainline/linux show <sha> -- <path>`
- Find the upstream commit for a fix by subject:
  `git -C /home/hwang4/work/mainline/linux log --oneline --grep "<subject>"`
- Check which release first contained a commit:
  `git -C /home/hwang4/work/mainline/linux describe --contains <sha>`
- Read the upstream version of a file for correctness comparison:
  `git -C /home/hwang4/work/mainline/linux show <ref>:<path>`

Treat this repo as read-only reference; never commit or fetch into it as part of
a review. If the path is missing, fall back to upstream URLs and note it.

## openEuler reference repo

A local openEuler kernel clone is available at:

- Path: `/home/hwang4/test/jinze/euler/linux-euler` (override with
  `JINZE_EULER_REPO`)
- Remote: `origin` (openEuler on atomgit). Default branch `OLK-6.6`; other
  release branches (`OLK-5.10`, `openEuler-*-LTS`, `master`) are present.

openEuler is another Kunpeng/ARM64-focused kernel, so it is a valuable
cross-reference for Kunpeng-specific drivers and backports. Use it read-only to:

- Find whether openEuler already carries an equivalent patch (avoid divergence)
  and how they solved it:
  `git -C /home/hwang4/test/jinze/euler/linux-euler log --oneline --grep "<subject>"`
- Compare a Kunpeng driver/file against openEuler's version:
  `git -C /home/hwang4/test/jinze/euler/linux-euler show OLK-6.6:<path>`
- Look up openEuler's handling of a specific subsystem/SoC quirk:
  `git -C /home/hwang4/test/jinze/euler/linux-euler log --oneline -- <path>`

openEuler carries many out-of-tree/SAUCE-style patches, so a match there is
supporting evidence, not upstream provenance. Prefer the mainline reference repo
for authoritative upstream origin; use openEuler to sanity-check Kunpeng-specific
behaviour and precedent. If the path is missing, note it and continue.

## Repository layout (Ubuntu kernel packaging)

- Source tree: standard Linux kernel layout (`arch/arm64/`, `drivers/`, etc.).
- `debian.kunpeng/` — the active packaging dir for this flavour:
  - `changelog` — release history; the top entry names the current version.
  - `config/` — kernel config; ABI and annotations.
- `debian.master/`, `debian/` — Ubuntu base packaging (usually not edited by
  customers).
- Config changes appear in the changelog as `[Config]` lines.

## Commit / provenance conventions (Ubuntu + DCO)

- Every commit needs a `Signed-off-by:` line (DCO). Customer commits should also
  keep the original author's `Signed-off-by` when a patch is backported.
- Ubuntu-specific commits are prefixed `UBUNTU:` (e.g. `UBUNTU: [Config] ...`,
  `UBUNTU: SAUCE: ...` for out-of-tree carried patches).
- Backported upstream commits should carry provenance:
  `(cherry picked from commit <sha>)` or `(backported from commit <sha>)` plus
  a note describing any conflicts resolved.
- A `Bug:`/`BugLink:` or `Link:` reference is expected for tracked fixes.

## Useful local commands

- Current version: top line of `debian.kunpeng/changelog`.
- Show a series: `git --no-pager log --oneline <base>..<branch>`.
- Diff a proposed branch: `git --no-pager diff <base>...<branch>`.
- Per-commit inspection: `git --no-pager show --stat <sha>`.
- Check a patch applies: `git apply --check <file.patch>` (or
  `git am --abort`-safe dry runs on a scratch branch).
- Config touched files live under `debian.kunpeng/config/`.

## Risk lenses (apply in every sub-skill)

- Scope: does the change stay within Kunpeng/ARM64-relevant code, or does it
  touch generic/core paths that could regress other flavours?
- ABI: does it change exported symbols / module ABI (Ubuntu tracks ABI)?
- Config: are `Kconfig`/config changes reflected in `debian.kunpeng/config`?
- Security: does it introduce or fix a CVE; any unsafe memory / locking / user
  input handling?
- Provenance: is upstream origin cited and is the DCO chain intact?
- Build/test: does it build for arm64 and is there a test or reproduction?
