---
doc_id: readme
version: 1
locale: en_US
---

# KabuForge documentation

<!-- section:contract -->
## Contract

KabuForge is a local-first quantitative research stack for Japanese equities: user-owned J-Quants or other local price data flows through factor and model research into backtests, portfolio/risk review, and broker planning. Price momentum is the default research strategy. The current source candidate is unpublished; read its version from `pyproject.toml` or `kabuforge doctor`. The [canonical homepage](https://kabuforge.com/) displays a generated version block from the same source. Published releases remain historical records and do not identify this candidate.

This is a research system, not a live-trading claim. Historical outputs are RESEARCH-ONLY with `pit_guarantee=false`; strict PIT, fresh forward validation, PAPER-READY status, and real terminal verification are not established. TOPIX is a price index without dividends and is aligned only on exact dates. The public build defaults Regime Off and does not include the private Regime bridge.

<a id="quick-start"></a>
### Quick start / CLI

Python 3.12 or later is required. The core package and each optional dependency group are defined in `pyproject.toml`; install only the groups needed for your selected workflow. The public source GUI/worker workflows and 14 CLI/MCP research routes have source-level validation. Clean-wheel and isolated installed-workflow acceptance are tracked separately; source screenshots do not certify an installed distribution. The current `0.2.0rc1` candidate is unpublished.

```shell
python -m pip install .
python -m pip install ".[gui,analytics,indicators,models,backends]"
kabuforge doctor
python -m framework_v2.workbench_qt
```

The GUI quick reference is the [three-language five-course guide](GUI_RESEARCH_COURSES.md); the bundled offline manual has 24 searchable chapters. It uses explicit user-owned CSV, Parquet, or completed manifests; no market cache, full report, model artifact, credential, or Paper ledger is bundled. For the current distinction between source implementation, runtime discovery, successful source runs, package acceptance, and broker verification, see the [integration matrix](INTEGRATIONS.md).

### Getting started

- [Quick start / CLI](#quick-start)
- [GUI courses and searchable manual](GUI_RESEARCH_COURSES.md)
- [Development](DEVELOPMENT.md)
- [Roadmap](ROADMAP.md)

### Concepts

- [Architecture](ARCHITECTURE.md)
- [Research correctness and data limits](RESEARCH_METHODOLOGY.md)
- [Integration capability matrix](INTEGRATIONS.md)

### APIs

- [Factors: registry and validators](FACTOR_API.md)
- [Strategies: decisions and targets](STRATEGY_API.md)
- [MCP: access and receipts](AGENT_API.md)
- [Execution: simulation and UNKNOWN](EXECUTION.md)
- [Broker mappings and mocks](BROKER_API.md)

### Validation

- [Validation and retained release limitations](RELEASE_PROCESS.md)
- [Python 3.12 release foundation CI](https://github.com/Siyuan-chat/KabuForge/actions/workflows/kabuforge.yml)
- [Release process](RELEASE_PROCESS.md)
- [Unpublished source candidate and version source](https://kabuforge.com/)

### Contribution

- [Contribution and license](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)

<!-- section:evidence -->
## Evidence

Source-level reference runs cover the local-cache, indicator, factor/model/engine, historical Paper, broker-preview, and sensitivity workflows described in the [courses](GUI_RESEARCH_COURSES.md) and [capability matrix](INTEGRATIONS.md), including the public GUI/worker routes and 14 CLI/MCP research routes. Clean-wheel and isolated installed-workflow acceptance receipts are tracked separately; source runs and screenshots alone are not installed-distribution certification. Broker mapping is offline; an explicitly requested read-only diagnostic is separate, and neither establishes a real terminal connection. Order submission and cancellation are disabled.

`kabuforge doctor` reports the version and local capabilities from the installed/source distribution. The [homepage](https://kabuforge.com/) version is generated from the project version source. See [releases](https://github.com/Siyuan-chat/KabuForge/releases) for historical published artifacts.

[English](../en_US/README.md) · [简体中文](../zh_CN/README.md) · [日本語](../ja_JP/README.md)
