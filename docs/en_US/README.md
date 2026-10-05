---
doc_id: readme
version: 1
locale: en_US
---

# KabuForge documentation

<!-- section:contract -->
## Contract

KabuForge is an open-source, local-first Japanese-equity research framework for researchers and developers exploring factors, strategies and reproducible backtests.

Package release `v0.1.1` is the current stable release ([GitHub Release](https://github.com/Siyuan-chat/KabuForge/releases/tag/v0.1.1)). The moving `main` branch is for development and may contain unreleased changes. Python, CLI, desktop GUI and MCP interfaces use shared application services.

The offline synthetic demo needs no data key; real market data access and credentials depend on the selected provider. Paper and backtest fills are simulations, not broker executions, and complete historical PIT certification is not provided.


<a id="quick-start"></a>
### Quick start / CLI

Python 3.12+

From a source checkout, run:

```shell
git clone --branch v0.1.1 --depth 1 https://github.com/Siyuan-chat/KabuForge.git
cd KabuForge
python -m pip install .
kabuforge doctor
kabuforge demo --out output/demo
kabuforge factors
kabuforge strategies
```

### Getting started

- [Quick start / CLI](#quick-start)
- [Development](DEVELOPMENT.md)

### Concepts

- [Architecture](ARCHITECTURE.md)
- [Research correctness and data limits](RESEARCH_METHODOLOGY.md)

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

### Contribution

- [Contribution and license](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)

<!-- section:evidence -->
## Evidence

`kabuforge doctor`, `kabuforge factors`, `kabuforge strategies`, `kabuforge demo` / Python 3.12+.

[English](../en_US/README.md) · [简体中文](../zh_CN/README.md) · [日本語](../ja_JP/README.md)
