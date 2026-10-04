# KabuForge

[Website](https://kabuforge.com/) · [Quickstart](https://kabuforge.com/docs/quickstart/) · [Documentation](https://kabuforge.com/docs/) · [日本語](https://kabuforge.com/ja/)

[English](README.md) · [简体中文](README.zh_CN.md) · [日本語](README.ja_JP.md)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/kabuforge/v2/logo-horizontal-dark.svg">
  <img width="420" alt="KabuForge" src="brand/kabuforge/v2/logo-horizontal-light.svg">
</picture>

**Reproducible quantitative research for Japanese equities.**

An open-source, local-first research framework for Japanese equities, with factor and strategy research, backtesting, local paper simulation, and MCP agent interfaces.

[Quick Start](#quick-start) · [Documentation](docs/en_US/README.md) · [Architecture](docs/en_US/ARCHITECTURE.md) · [Releases](https://github.com/Siyuan-chat/KabuForge/releases)

Current package version: **0.1.0rc1**. Research and local simulation only; real broker order submission is disabled. The published `v0.1.0` GitHub Release retains RC package artifacts and the historical MIT license.

[![CI](https://github.com/Siyuan-chat/KabuForge/actions/workflows/kabuforge.yml/badge.svg)](https://github.com/Siyuan-chat/KabuForge/actions/workflows/kabuforge.yml)
[![License: AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-292F33)](LICENSE)
[![Package RC](https://img.shields.io/badge/package-0.1.0rc1-E65324)](https://github.com/Siyuan-chat/KabuForge/releases/tag/v0.1.0-rc.1)

## What is KabuForge?

KabuForge connects factor and strategy research with portfolio construction, risk controls, broker-neutral order planning, historical backtesting, and local paper simulation. Shared application services are accessible through Python, CLI, desktop GUI, and MCP-compatible agents.

```text
Factor → Strategy → TargetPortfolio → Risk → Planner → OrderIntent
```

## Current capabilities

| Capability | Status and boundary | Evidence |
| --- | --- | --- |
| PIT visibility gates | Checks declared `available_at` against decision time; no complete historical PIT certification | [Docs](docs/en_US/RESEARCH_METHODOLOGY.md) |
| Factor / Strategy extensions | Registered, versioned implementations and required validators | [Docs](docs/en_US/FACTOR_API.md) |
| Portfolio / Risk / Planner | Targets, risk constraints and broker-neutral order intents | [Docs](docs/en_US/ARCHITECTURE.md) |
| Historical backtest | Local simulation with explicit research and execution price semantics | [Docs](docs/en_US/EXECUTION.md) |
| Local paper | Local account/journal simulation; simulated fills are not broker fills | [Docs](docs/en_US/EXECUTION.md) |
| MCP agents | R0/R1 inspection and local research by default; R2 paper writes require explicit opt-in | [Docs](docs/en_US/AGENT_API.md) |
| Broker mappings / mocks | Contract and mock validation layer; real transport remains unverified | [Docs](docs/en_US/BROKER_API.md) |
| Real broker orders | Not enabled in this RC; reserved R3 interfaces are disabled | [Docs](docs/en_US/AGENT_API.md) |

<a id="quick-start"></a>
## Quick start

Python 3.12+

```shell
git clone https://github.com/Siyuan-chat/KabuForge.git
cd KabuForge
python -m pip install .
kabuforge doctor
kabuforge demo --out output/demo
kabuforge factors
kabuforge strategies
```

The demo is synthetic and offline: no market data, J-Quants key or broker account is needed. Install `.[gui]` instead of `.` for the optional desktop GUI; on Windows launch `Launch_KabuForge.bat`.

### Agent / MCP

Start a workspace-bounded stdio MCP server. Paper mutations require `--enable-paper`; this grants only local simulation access.

```shell
kabuforge mcp --workspace output/agent_workspace
kabuforge mcp --workspace output/agent_workspace --enable-paper
```

## Why KabuForge?

KabuForge keeps research ideas in explicit Factor and Strategy contracts, then connects them to portfolio, risk and broker-neutral planning through shared application services.

| Design | What it enables |
| --- | --- |
| Extensible research | Registered, versioned factors and strategies without rewriting the execution engine |
| One decision pipeline | Research decisions remain separate from execution constraints and order construction |
| Shared interfaces | Python, GUI, CLI and MCP use the same application contracts; agent access adds workspace and receipt boundaries |
| Inspectable decisions | Declared visibility times, content identities and durable receipts support review, with external-data limits kept explicit |

## Bring your own Factor and Strategy

```text
FactorSpec + FactorContext → FactorResult
FactorResult(s) → StrategyDecision → TargetPortfolio
```

Trusted application code registers factor implementations with spec validators, and strategy factories by implementation ID and version. Unknown or duplicate identities fail; configuration cannot request arbitrary Python imports or evaluation. Strategies receive registered factor results, PIT context, state and decision identity, then return a target or no-rebalance decision. Risk policy and the planner apply execution constraints afterwards.

[Factor contracts](docs/en_US/FACTOR_API.md) · [Strategy contracts](docs/en_US/STRATEGY_API.md)

## Architecture and interfaces

```mermaid
flowchart TD
  Python[Python] --> App[Application Services]
  GUI[GUI] --> App
  CLI[CLI] --> App
  MCP[MCP Agent] --> App
  Data[PIT Data Snapshot] --> Factor[Factor Registry]
  App --> Factor
  Factor --> Strategy[Strategy Registry]
  Strategy --> Target[TargetPortfolio]
  Target --> Risk[Risk Policy]
  Risk --> Planner[Order Planner]
  Planner --> Intent[OrderIntent]
  Intent --> Backtest[Historical Backtest]
  Intent --> Paper[Local Paper Simulation]
  Intent -. reserved / disabled .-> Broker[Broker Adapter]
```

```text
Python / GUI / CLI / MCP
           ↓
   Application Services
           ↓
Research / Risk / Planning
```

Shared application services validate, decide and plan; this boundary does not submit broker orders or write an execution ledger. Historical and local paper workflows share research and decision semantics while their execution prices and simulated fills remain explicit. R0/R1 MCP tools are enabled by default, R2 paper writes require opt-in, and R3 external actions remain disabled in this RC.

[Architecture](docs/en_US/ARCHITECTURE.md) · [Agent boundaries](docs/en_US/AGENT_API.md)

## Research correctness

- Timezone-aware `available_at` declares when an input became visible; future rows require a decision-time gate.
- Factor, data snapshot and configuration identities make a run inspectable; decision and MCP call receipts retain evidence.
- Research prices select targets; later execution prices must not reselect an earlier target.
- `UNKNOWN` belongs to the execution/reconciliation contract for uncertain submission outcomes. It is not proof that live broker submission is enabled, and must not trigger a blind retry.
- Synthetic examples are labeled and do not establish performance. Vendor timing, revisions, survivorship, corporate actions and universe construction still need separate checks.

[Research Methodology](docs/en_US/RESEARCH_METHODOLOGY.md) · [Architecture](docs/en_US/ARCHITECTURE.md) · [Factor API](docs/en_US/FACTOR_API.md) · [Strategy API](docs/en_US/STRATEGY_API.md) · [Agent API](docs/en_US/AGENT_API.md)

## Documentation and validation

[Documentation](docs/en_US/README.md) · [CI](https://github.com/Siyuan-chat/KabuForge/actions/workflows/kabuforge.yml) · [Release validation](docs/RELEASE_VALIDATION.md) · [Changelog](docs/en_US/CHANGELOG.md) · [Security](SECURITY.md) · [Contributing](docs/en_US/CONTRIBUTING.md)

<details>
<summary>Workflow demo / 流程演示 / フローのデモ</summary>

This is a historical interface/workflow recording. Its historical NAV does not represent current public factors, the new synthetic CLI demo, or investment performance. [Demo context](docs/demos/en_US/index.html).

![KabuForge workflow](docs/demos/en_US/workflow.gif)

</details>

## Citation

For research or technical writing, cite this repository using [CITATION.cff](CITATION.cff). No DOI is assigned.

## License

Current project-owned code, documentation and assets are licensed under **AGPL-3.0-only**. See [LICENSE](LICENSE) and [licensing scope and retained notices](PROJECT_LICENSING.md). Historical tags, wheels, source archives and checksums retain their original licenses; the existing `v0.1.0-rc.1` and `v0.1.0` Releases remain MIT. New AGPL distributions require a future version.

Research and simulation software; not investment advice. See [DISCLAIMER.md](DISCLAIMER.md) and [SECURITY.md](SECURITY.md).
