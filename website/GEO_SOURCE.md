# GEO source of truth and maintenance

This site describes the current public KabuForge project. Use `docs/geo-facts.json` as the checked-in stable-release snapshot for the current version, tag, URL and verification metadata. Keep public site version and license claims aligned with that release before publishing content.

## Authoritative inputs

- `docs/geo-facts.json`: canonical checked-in snapshot for `current_release` version, tag, release URL, commit and verification metadata; `historical_release` preserves historical version/license context; `current_license` records current project-owned licensing.
- The KabuForge software repository root: `README.md`, `README.ja_JP.md`, `README.zh_CN.md`, `CITATION.cff`, and localized changelogs provide stable release labels, citations and product boundaries. `pyproject.toml` describes the current source checkout; its package version may be an unreleased development version and can lead the stable release.
- The matching tagged source tree and its tests: implementation claims, including order behavior, MCP permissions, and point-in-time checks.
- The website source tree: `src/data/pages.json`, `src/pages/`, `src/layouts/Layout.astro`, and `public/llms.txt` carry website copy, metadata, structured facts, and the machine-readable summary.
- The matching GitHub Release and source tag: stable release identity, publication state, and release notes.

The stable release is the `current_release` recorded in `docs/geo-facts.json`. Historical `v0.1.0` release materials retain their own RC artifacts and MIT terms; do not treat them as current project licensing or as evidence for current behavior. Update only from evidence for the relevant release, and keep development builds distinct from stable tags.

## Update procedure

1. Verify a stable release from its repository tag, source tag metadata and GitHub release record. Update `docs/geo-facts.json` with the current stable version, tag, matching release URL and commit, verification date/source, current source-branch package version, and any historical release identity that changed. Do not copy the development package version into `current_release` just because `main` is ahead. From the repository root, capture the GitHub latest-release API JSON and run `python tools/check_geo_consistency.py --website website --release-json <snapshot.json>`. If the website is checked out separately (for example in Sites), pass its absolute path with `--website <absolute-site-path>`.
2. Update the English and Japanese homepages, docs overview, release page, header/schema facts, and `public/llms.txt` together. Cite implementation details to matching tagged docs or code; preserve explicit simulation, broker, data, and PIT limitations.
3. Run `python tools/check_geo.py`, `python -m unittest discover -s tools -p 'test_check_geo*.py' -q`, and `python tools/check_geo_consistency.py --website website [--release-json <snapshot.json>]`, followed by the website build and website checks. These local checkers are deterministic and make no network calls themselves; the optional release JSON is a separately captured snapshot. CI may fetch a latest-release snapshot before running them. Passing local consistency checks alone does not verify live GitHub or production website state.
4. Review rendered pages and the release snapshot before any separately authorized publication step.

Clear metadata and crawl access can help machines interpret the site, but neither this process nor the checker guarantees indexing, ranking, citations, or answers from any search or AI platform.
