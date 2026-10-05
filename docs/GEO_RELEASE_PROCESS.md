# Public release information and synchronization

This guide keeps public project descriptions clear for people and search systems. Treat the current stable release snapshot (tag, release metadata and artifacts) as the source of truth for the stable package. The `main` branch and its `pyproject.toml` describe development source and may move ahead of the stable release. The website is a separate published surface and must not be described as verified just because repository files link to it.

## Version meanings

- **Current stable package:** the version and tag in the current stable GitHub Release snapshot, with its published artifacts. The README stable-install command must pin that tag. Update the release snapshot and public references together when a new stable package is approved.
- **Historical release:** an existing tag and its attached source, wheels, checksums, and license terms. Keep those artifacts and descriptions historically accurate; never rewrite or replace them to match the current version.
- **Development source:** the moving `main` branch. It can include unreleased changes and should be labeled as development; it is not a stable package version.
- **Release candidate:** a prerelease identified by its own tag and package metadata. Do not describe an RC as the current stable release after a stable release exists.

## Release synchronization checklist

1. Confirm the approved source commit, package metadata, release tag, license scope, and artifact identities. Follow [Release Process](en_US/RELEASE_PROCESS.md) and the [release template](https://github.com/Siyuan-chat/KabuForge/blob/main/.github/RELEASE_TEMPLATE.md); the release documentation does not authorize publishing.
2. Set `CITATION.cff` `version` to the cited software release (not an unrelated development commit). Keep `url` on the official project website and `repository-code` on GitHub. `pyproject.toml` records the source checkout's package version and may identify unreleased development work.
3. Update all three root READMEs together: current version and release links, stable tag install command, development-branch note, limitations, and historical release/licensing statements. Preserve the capability tables and brand assets.
4. Run the repository documentation and release checks, including `python tools/check_docs.py`; inspect the rendered website build and its own checks separately when website content changes.
5. After the approved release is published, verify the GitHub tag and artifacts directly. Update the website only through its own reviewed publication flow, then check the live pages and links. A successful local build cannot establish that the live website is current or reachable. See the [manual GEO answer evaluation](GEO_EVAL.md); its questions are a benchmark, not evidence that an evaluation has been run.

## Maintaining the GEO facts snapshot

`docs/geo-facts.json` is a checked-in snapshot of public identities, not a network client or a claim that the production website was checked. Keep `repository`, `website`, and `documentation` aligned with project metadata. `source_branch` and `source_branch_package_version` describe the development checkout (`main` and `pyproject.toml`); this package version may lead the stable release. `current_release` records the verified stable version, tag, release URL, source commit, verification date, and verification source. `historical_release` preserves the prior release identity and license; `current_license` describes current project-owned material.

When a stable release changes, first inspect the GitHub tag, release state and attached artifacts using an authorized read-only source, then update the stable-release fields and verification metadata from that evidence. Update the source-branch package version from the checkout independently. Do not mark website production state verified from repository or CI results. The checks below perform no network access and only check local consistency; they do not refresh the snapshot or verify live GitHub/site state.

Run the deterministic local checks with Python 3.12 or newer:

```shell
python tools/check_geo.py
python -m unittest discover -s tools -p test_check_geo.py -q
python tools/check_docs.py
```

The workflow runs the GEO checker and negative fixtures, not a live-site or release API test. These commands do not establish external release state; record that verification separately in `geo-facts.json`.

## Website boundary

The repository currently links to `https://kabuforge.com/`, but this file does not certify the live website's content, ownership, availability, indexing, analytics, or synchronization with GitHub. Do not infer an organizational relationship between KabuForge and any other project from visual similarity, links, or naming. Report website state as unverified until the live pages have been independently checked after publication.
