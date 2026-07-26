# Releasing

This document describes how to cut a release of Messenger.

## Versioning

Messenger uses [Semantic Versioning](https://semver.org):

- **PATCH** (`0.4.1`) — a bug fix. Backward compatible. Any bug fix that lands on `main` gets a PATCH release within a few days.
- **MINOR** (`0.5.0`) — new features. Backward compatible. Features accumulate on `main` between MINOR releases.
- **MAJOR** (`1.0.0`) — a breaking change. Reserved for wire-protocol incompatibility between server and client.
- **Pre-release** (`0.6.0-rc.1`) — a release candidate for a MINOR (or MAJOR) that hasn't stabilized yet. Optional; used only when a change is risky enough to want tester feedback before it goes to everyone.

Pre-release identifiers **must be dot-separated** (`-rc.1`, not `-rc1`). Without the dot, SemVer sorts `rc.10` before `rc.2` alphabetically.

## When to cut which

- **Fix landed on `main`** → cut PATCH. If features have also landed on `main` since the last release, cut MINOR instead (a PATCH release must contain only fixes).
- **Feature batch feels ready** → cut MINOR.
- **Risky feature or refactor about to ship** → cut `X.Y.0-rc.1` first, gather feedback, iterate rcs, then cut `X.Y.0`.
- **Wire-protocol breaking change** → cut MAJOR.

## Release workflow

Two GitHub Actions, both manual:

- **Draft Release** — opens a PR that bumps `messenger/__init__.py` and updates `CHANGELOG.md`. The PR body includes a checklist that reminds you to clean up the changelog section and update `README.md` (banner version, any references to the old version) before merging.
- **Publish Release** — after the PR is merged, tags the commit, creates a GitHub Release, and (optionally) publishes to PyPI.

Both are triggered from the repo's Actions tab → "Run workflow."

**Publish Release has a checkbox** for whether to publish to PyPI (checked by default). Uncheck it to only tag + create the GitHub Release, skipping the PyPI upload entirely. Useful when PyPI Trusted Publishing isn't set up yet or when you deliberately want a GitHub-only release.

### Standard release flow (PATCH or MINOR)

1. Land your commits on `main` as normal.
2. Actions → **Draft Release** → enter version (e.g. `0.4.1`) → Run.
3. Review the PR. Clean up the auto-drafted changelog section under `## [0.4.1]` — delete the `AUTO-DRAFT START/END` block after copying anything useful out of it.
4. Squash-merge the PR.
5. Actions → **Publish Release** → leave "Publish to PyPI" checked → Run.
6. Done. Tag `v0.4.1` exists, GitHub release is published, PyPI has the new version.

### Release with pre-release candidates

1. Land the risky change on `main`.
2. Draft Release → `0.6.0-rc.1` → clean up `[Unreleased]` in the PR → squash-merge.
3. Publish Release → tags `v0.6.0-rc.1`, GitHub marks it pre-release, PyPI accepts as pre-release (users need `pip install messenger --pre` to get it).
4. Fixes land on `main`.
5. Draft Release → `0.6.0-rc.2` → merge → Publish Release.
6. Repeat as needed.
7. When solid: Draft Release → `0.6.0` (no suffix) → merge → Publish Release. Final release. `pip install messenger` now returns `0.6.0`.

## `CHANGELOG.md` behavior

The changelog uses [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) format with a `## [Unreleased]` accumulator at the top.

- You can edit `[Unreleased]` directly on `main` at any time to jot notes.
- **Non-pre-release** Draft (PATCH/MINOR/MAJOR): `[Unreleased]` is promoted into a new `## [X.Y.Z] - <date>` section and reset to empty.
- **Pre-release** Draft (rc/beta): `[Unreleased]` is preserved; the auto-draft comment block inside it is refreshed from git log.

Publish Release reads release notes from:

- `## [X.Y.Z]` section for finals/PATCHes/MINORs.
- `## [Unreleased]` section for pre-releases.

The `<!-- AUTO-DRAFT ... -->` comment block is stripped before notes are attached to the GitHub Release or PyPI description.

### Section conventions

Use `### Added`, `### Changed`, `### Fixed` for most entries. `### Deprecated`, `### Removed`, `### Security` are available when they apply.

## Pre-flight checklist

Before the first PyPI publish ever succeeds, three things must be done. None depend on which release you're cutting.

1. **Fix the version regex in `setup.py`.** The current regex at [setup.py:22](../setup.py) accepts `0.4.0` but rejects `0.4.0-rc.1`. Broaden it to accept anything between the quotes. Without this fix, any pre-release publish will fail at the wheel-build step because `setup.py` can't parse its own version.
2. **Claim the PyPI package name.** `messenger` on PyPI was claimed in 2016 by an unrelated abandoned project. Either:
   - File a [PEP 541](https://peps.python.org/pep-0541/) request at [github.com/pypi/support](https://github.com/pypi/support) (4–8 week wait), or
   - Rename the dist in `setup.py` to something available (e.g. `messenger-tunneling`). The import name stays `messenger`.
3. **Configure PyPI Trusted Publishing.** On the PyPI project's settings page → Publishing → Add trusted publisher:
   - Owner: `skylerknecht`
   - Repository: `messenger`
   - Workflow filename: `release-publish.yml`
   - Environment: (leave blank)

Once (1) and (3) are done, `pypa/gh-action-pypi-publish` in the publish workflow can upload without any stored API tokens.

## Troubleshooting

- **Publish fails with "tag already exists"**: someone (probably you) already ran Publish for this version. Bump the version and re-run Draft Release. There's no way to re-publish the same version to PyPI even if the first publish failed — PyPI reserves the version number permanently.
- **Publish fails with "no section [X.Y.Z] found"**: the Draft PR wasn't merged, or the version in `__init__.py` doesn't match a section in `CHANGELOG.md`.
- **Publish fails with "section [Unreleased] is empty"**: the pre-release has no release notes. Add bullets under `[Unreleased]` and re-run.
- **`python -m build` step crashes on a pre-release version**: pre-flight item (1) hasn't been done yet — fix the `setup.py` regex.
- **PyPI upload step fails**: check Trusted Publishing is configured for this project on PyPI, and that the version hasn't already been uploaded. To salvage the release: since the tag and GitHub Release already succeeded before the PyPI step, the version is "half-published." Bump to the next version and re-run Draft + Publish; treat the failed one as a rehearsal.
- **Want to release to GitHub but not PyPI**: uncheck "Publish to PyPI" when running Publish Release. Tag + GitHub Release still happen; PyPI is skipped cleanly.

## Attribution

- **Commits in the release PR** are authored by whoever clicked "Run workflow" (via `github.actor`).
- **The PR itself** is opened by `github-actions[bot]` (this is a limitation of the default GITHUB_TOKEN; publishing under a personal account would require a personal access token stored as a secret, which adds security risk for no real benefit).
- **Squash-merging** the release PR produces a single commit on `main` authored by you.
- **Tags** are annotated tags pushed by the workflow with your user identity.

## What lives where

- `messenger/__init__.py` — single source of truth for `__version__`.
- `CHANGELOG.md` — human-readable release notes.
- `.github/workflows/release-draft.yml` — opens the release PR.
- `.github/workflows/release-publish.yml` — tags, creates GitHub Release, publishes to PyPI.
- Tags: `vX.Y.Z` on the release commit.
