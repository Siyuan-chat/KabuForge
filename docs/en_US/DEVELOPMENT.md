---
doc_id: development
version: 1
locale: en_US
---

# Development

<!-- section:contract -->
## Contract

Develop against the package boundary, not GUI internals or configuration-driven imports. The existing `ApplicationService.register_factor(id, version, function, validator)` and `StrategyRegistry.register(StrategySpec, factory)` APIs remain supported; validators are mandatory and duplicate identities are rejected. The newer `ResearchApplicationService` is a workspace-bounded facade for supported fixed research operations. It accepts explicit file references and recipes, delegates selected optional work to static workers, and retains request/source hashes, receipts, and failure logs. GUI, CLI, and MCP access is governed by their own supported adapters and allowlists; do not assume every legacy screen or command is routed through this facade. It does not accept user Python, arbitrary module paths, or an interpreter command.

Use deterministic local fixtures. Local-cache research does not infer historical `available_at`; every such result remains RESEARCH-ONLY with `pit_guarantee=false`. Keep raw research data, credentials, broker transports, and private implementations outside a public distribution. A simulated fill, planned intent, or successful CLI exit is not proof of live execution.

The public source has validated GUI and worker workflows for explicit local-data selection, default price-momentum research, indicators, factor/model/engine research, reports, isolated Historical Paper, and broker mapping/read-only boundaries. Python APIs and 14 fixed CLI/MCP research routes are also source-validated. Read the [integration matrix](INTEGRATIONS.md) and the [five GUI research courses](GUI_RESEARCH_COURSES.md) before changing a workflow.

<!-- section:evidence -->
## Evidence

The public package is `kabuforge`, requires Python 3.12+, and uses AGPL-3.0-only for project-owned material; retained third-party notices remain applicable. The candidate version is `0.2.0rc1` and is unpublished. Its command entry point is `kabuforge = kabuforge.cli:main`. Public source provenance is pinned by `public_source_manifest.json`; source checks do not by themselves certify a wheel installation or GUI run.

Install the GUI extra in a Python 3.12 environment. Optional groups are declared in `pyproject.toml` (`analytics`, `indicators`, `models`, `backends`); install only the group needed for a workflow. Worker receipts, not package metadata or capability discovery alone, show whether a selected optional operation actually ran.

```powershell
python -m pip install -e ".[gui]"
python -m framework_v2.cli --help
python -B -m unittest discover -s framework_v2/tests -q
python -B -m unittest discover -s tools/tests -p "test_sync_version.py" -q
```

From a source checkout, the desktop workbench can be started interactively with:

```powershell
python -B -m framework_v2.workbench_qt
```

This command opens the interactive GUI. It is not a headless or unattended test command. A distribution acceptance claim must be tied to the exact built wheel filename, SHA-256, version, Python/platform, and installed module origins; run the applicable GUI/worker checks against that installed artifact. Source-checkout screenshots and source tests do not certify an installed wheel. Version `0.2.0rc1` is unpublished.
