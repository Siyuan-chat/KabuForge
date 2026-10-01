# KabuForge

[English](README.md) · [简体中文](README.zh_CN.md) · [日本語](README.ja_JP.md)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/kabuforge/v1/logo-horizontal-dark.svg">
  <img width="420" alt="KabuForge" src="brand/kabuforge/v1/logo-horizontal-light.svg">
</picture>

**可复现的日本股票量化研究。**

开源、本地优先的日本股票研究框架，涵盖因子与策略研究、历史回测、本地纸上模拟及 MCP agent 接口。

[Quick Start](#quick-start) · [Documentation](docs/zh_CN/README.md) · [Architecture](docs/zh_CN/ARCHITECTURE.md) · [Releases](https://github.com/Siyuan-chat/KabuForge/releases)

当前包版本为 **0.1.0rc1**。仅用于研究与本地模拟，真实券商下单未启用。已发布的 GitHub `v0.1.0` Release 保留 RC 包附件及历史 MIT 许可。

[![CI](https://github.com/Siyuan-chat/KabuForge/actions/workflows/kabuforge.yml/badge.svg)](https://github.com/Siyuan-chat/KabuForge/actions/workflows/kabuforge.yml)
[![License: AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-292F33)](LICENSE)
[![Package RC](https://img.shields.io/badge/package-0.1.0rc1-E65324)](https://github.com/Siyuan-chat/KabuForge/releases/tag/v0.1.0-rc.1)

## KabuForge 是什么？

KabuForge 将因子与策略研究连接到组合构建、风险控制、券商中立订单规划、历史回测和本地纸上模拟。Python、CLI、桌面 GUI 与 MCP agent 共用同一应用服务。

```text
Factor → Strategy → TargetPortfolio → Risk → Planner → OrderIntent
```

## 当前能力

| 能力 | 状态与边界 | 证据 |
| --- | --- | --- |
| PIT 可见性门控 | 检查声明的 `available_at` 与决策时间；不代表完整历史 PIT 认证 | [Docs](docs/zh_CN/RESEARCH_METHODOLOGY.md) |
| Factor / Strategy 扩展 | 注册、版本化实现与必需 validator | [Docs](docs/zh_CN/FACTOR_API.md) |
| Portfolio / Risk / Planner | 目标组合、风险约束与券商中立订单意图 | [Docs](docs/zh_CN/ARCHITECTURE.md) |
| 历史回测 | 本地模拟，明确研究价与执行价语义 | [Docs](docs/zh_CN/EXECUTION.md) |
| 本地纸上模拟 | 本地账户与日志模拟；模拟成交不等于券商成交 | [Docs](docs/zh_CN/EXECUTION.md) |
| MCP agents | 默认 R0/R1 检查和本地研究；R2 paper 写入必须显式启用 | [Docs](docs/zh_CN/AGENT_API.md) |
| 券商映射 / mocks | 契约与 mock 验证层；真实 transport 尚未验证 | [Docs](docs/zh_CN/BROKER_API.md) |
| 真实券商下单 | 当前 RC 未启用；预留 R3 接口处于禁用状态 | [Docs](docs/zh_CN/AGENT_API.md) |

<a id="quick-start"></a>
## 快速开始

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

demo 使用离线合成数据，无需市场数据、J-Quants 密钥或券商账户。如需桌面 GUI，将安装参数 `.` 改为 `.[gui]`；Windows 可启动 `Launch_KabuForge.bat`。

### Agent / MCP

启动受工作区边界约束的 stdio MCP 服务。paper 写入须加 `--enable-paper`，仅开放本地模拟权限。

```shell
kabuforge mcp --workspace output/agent_workspace
kabuforge mcp --workspace output/agent_workspace --enable-paper
```

## 研究正确性

- 带时区的 `available_at` 声明输入何时可见；未来记录须通过决策时间门控。
- 因子、数据快照与配置身份支持检查运行来源；决策与 MCP 调用 receipts 保留证据。
- 研究价格决定目标；之后的执行价格不得重新选择此前的目标。
- `UNKNOWN` 属于执行与对账契约，表示提交结果不确定；不代表已启用真实券商提交，不得据此盲目重试。
- 合成示例须明确标识，不能证明绩效。供应商时间、历史修订、幸存者偏差、公司行为和股票池构建仍须另外核验。

[Research Methodology](docs/zh_CN/RESEARCH_METHODOLOGY.md) · [Architecture](docs/zh_CN/ARCHITECTURE.md) · [Factor API](docs/zh_CN/FACTOR_API.md) · [Strategy API](docs/zh_CN/STRATEGY_API.md) · [Agent API](docs/zh_CN/AGENT_API.md)

## 文档与验证

[Documentation](docs/zh_CN/README.md) · [CI](https://github.com/Siyuan-chat/KabuForge/actions/workflows/kabuforge.yml) · [Release validation](docs/RELEASE_VALIDATION.md) · [Changelog](docs/zh_CN/CHANGELOG.md) · [Security](SECURITY.md) · [Contributing](docs/zh_CN/CONTRIBUTING.md)

<details>
<summary>Workflow demo / 流程演示 / フローのデモ</summary>

![KabuForge workflow](docs/demos/zh_CN/workflow.gif)

</details>

## 引用

用于研究或技术写作时，请按 [CITATION.cff](CITATION.cff) 引用本仓库。项目未分配 DOI。

## 许可证

当前项目自有代码、文档与资产采用 **AGPL-3.0-only**。见 [LICENSE](LICENSE) 及[许可范围与保留通知](LICENSE_SCOPE.md)。历史 tag、wheel、源码包和校验和保持原许可；既有 `v0.1.0-rc.1` 与 `v0.1.0` Release 仍为 MIT。未来 AGPL 发行物须使用新版本。

本软件用于研究与模拟，不构成投资建议。见 [DISCLAIMER.md](DISCLAIMER.md) 与 [SECURITY.md](SECURITY.md)。
