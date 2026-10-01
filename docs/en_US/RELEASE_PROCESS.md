---
doc_id: release_process
version: 1
locale: en_US
---

# Release Process

<!-- section:contract -->
## Contract

The public RC is `0.1.0rc1`, package `kabuforge`, published as GitHub pre-release `v0.1.0-rc.1`. Its public factor and runtime sources remain pinned to the already-published baseline. The private local workspace is a separate distribution and is never an input to public factor packaging. Publish only after tests, independent wheel installation, source/wheel/sdist boundary audits and CI pass. No release authorizes trading.

<!-- section:evidence -->
## Evidence

`public_source_manifest.json` pins normalized source hashes; `tools/check_public_distribution.py` rejects provenance changes, private root runtimes, generated state and credentials. The release assets include the public wheel, source archive and their checksums. GitHub CI verifies Windows/Ubuntu, API/CLI/MCP and document parity. R3 remains absent by default and its optionally exposed hooks remain disabled.
