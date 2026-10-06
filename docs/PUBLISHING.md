# Publishing preparation

The `0.2.0rc1` candidate is unpublished. Do not claim `pip install kabuforge`
works until the intended artifact is on PyPI and clean installation passes.
Candidates require `--pre` or an explicit version. Python 3.12+ is required.

## PyPI gates

1. Confirm ownership/availability of `kabuforge` and select the release version.
   Synchronize package version and `server.json` before building.
2. Run `python -m build` and `python -m twine check dist/*`; inspect metadata,
   notices, resources and public-source checks.
3. Install the exact wheel in a clean Python 3.12 environment. Run `pip check`,
   `kabuforge doctor`, demo, MCP handshake and canonical recipes outside the
   checkout. Record hashes and imported module origins. GUI and optional worker
   acceptance remain separate artifact-specific gates.
4. Configure a pending Trusted Publisher for a first release (or a publisher on
   the owned existing project): owner `Siyuan-chat`, repository `KabuForge`,
   workflow `publish-pypi.yml`, environment `pypi`. Set environment reviewers.
5. Activate a reviewed workflow only after acceptance: separate build
   (`contents: read`) and publish (`id-token: write`, environment `pypi`) jobs;
   download the exact checked artifacts and use `pypa/gh-action-pypi-publish`.
   Pin actions to reviewed commits. No token belongs in the repository; do not
   rebuild in the publish job. This change activates no publishing workflow.
6. Verify installation from PyPI and record uploaded hashes.

Sources: [publisher setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/),
[publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## Official MCP Registry gates

`server.json` is a candidate manifest, not a registered listing. Publish the
referenced PyPI version first. Authenticate `io.github.Siyuan-chat` with the
official `mcp-publisher` GitHub login flow. Validate against the pinned schema
and official Registry validation endpoint before publishing the reviewed version.
Inspect the listing and test the resulting uvx command with an absolute workspace.

PyPI ownership verification requires `mcp-name: io.github.Siyuan-chat/kabuforge`
in the package long description. The homepage contains only a hidden verification
comment. Keep default paper-write opt-out and RESEARCH-ONLY / `pit_guarantee=false`.

Sources: [Registry requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/official-registry-requirements.md),
[PyPI verification](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx),
[schema](https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json).
