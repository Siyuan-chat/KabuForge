# GEO source of truth and maintenance

This site describes the current public KabuForge project. Keep version and license claims aligned with the matching source release before publishing content.

## Authoritative inputs

- The KabuForge software repository root: `pyproject.toml`, `README.md`, `README.ja_JP.md`, `README.zh_CN.md`, `CITATION.cff`, and localized changelogs are the release metadata and product-boundary sources.
- The matching tagged source tree and its tests: implementation claims, including order behavior, MCP permissions, and point-in-time checks.
- The website source tree: `src/data/pages.json`, `src/pages/`, `src/layouts/Layout.astro`, and `public/llms.txt` carry website copy, metadata, structured facts, and the machine-readable summary.
- The matching GitHub Release and source tag: stable release identity, publication state, and release notes.

The current stable release is v0.1.1 (package version 0.1.1). Historical v0.1.0 release materials retain their own RC artifacts and MIT terms; do not treat them as current project licensing or as evidence for current behavior. Update only from evidence for the relevant release, and keep development builds distinct from stable tags.

## Update procedure

1. Verify a stable release from the repository tag, source package metadata, and release record. From the KabuForge software repository root, capture the GitHub latest-release API JSON and run `python tools/check_geo_consistency.py --website website --release-json <snapshot.json>`. If the website is checked out separately (for example in Sites), pass its absolute path with `--website <absolute-site-path>`.
2. Update the English and Japanese homepages, docs overview, release page, header/schema facts, and `public/llms.txt` together. Cite implementation details to matching tagged docs or code; preserve explicit simulation, broker, data, and PIT limitations.
3. Run the source consistency checker, website build, and website checks. The checker is deterministic and does not use a language model.
4. Review rendered pages and the release snapshot before any separately authorized publication step.

Clear metadata and crawl access can help machines interpret the site, but neither this process nor the checker guarantees indexing, ranking, citations, or answers from any search or AI platform.
