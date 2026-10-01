---
doc_id: readme
version: 1
locale: en_US
---

# KabuForge documentation

<!-- section:contract -->
## Contract

Choose a route below. Package version is 0.1.0rc1; the published v0.1.0 Release keeps RC artifacts. No real trading or complete historical PIT certification is provided.


From a source checkout, run:

```shell
python -m pip install .
kabuforge doctor
kabuforge demo --out output/demo
kabuforge factors
kabuforge strategies
```

### Getting started

- [Quick start / CLI](DEVELOPMENT.md)
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
