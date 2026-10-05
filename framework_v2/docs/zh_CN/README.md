---
doc_id: readme
version: 1
locale: zh_CN
---

# KabuForge 文档

<!-- section:contract -->
## 契约

KabuForge 是面向日本股票的本地优先量化研究栈：用户自有的 J-Quants 或其他本地行情进入因子与模型研究，再进入回测、组合与风险审阅、券商规划。默认研究策略是价格动量。当前源码候选版本尚未发布；请从 `pyproject.toml` 或 `kabuforge doctor` 查询版本。[官方首页](https://kabuforge.com/)显示由同一来源生成的版本信息。已发布版本仅代表历史发行，不标识当前候选源码。

这是研究系统，不代表实盘交易。历史输出均为 RESEARCH-ONLY，`pit_guarantee=false`；尚未证明严格 PIT、全新前向验证、PAPER-READY 或真实终端连接。TOPIX 是不含分红的价格指数，只按完全匹配的日期连接。公开版本默认关闭 Regime，不包含私有 Regime 桥接。

<a id="quick-start"></a>
### 快速开始 / CLI

需要 Python 3.12 或更高版本。核心依赖和可选依赖组定义在 `pyproject.toml`，只安装当前工作流所需的依赖组。公开源码中的 GUI/worker 工作流和 14 条 CLI/MCP 研究路由已经过源码级验证。干净 wheel 与隔离环境安装工作流的验收凭证单独跟踪；源码截图不能证明已安装发行包通过验收。当前 `0.2.0rc1` 候选尚未发布。

```shell
python -m pip install .
python -m pip install ".[gui,analytics,indicators,models,backends]"
kabuforge doctor
python -m framework_v2.workbench_qt
```

GUI 操作步骤见[三语五课程指南](GUI_RESEARCH_COURSES.md)；随包离线手册有 24 个可搜索章节。输入须由用户明确选择 CSV、Parquet 或已完成的 manifest；不会随包提供行情缓存、完整报告、模型文件、凭证或 Paper 账本。源码实现、运行时可发现性、源码运行证据、安装包验收与券商验证的区别，见[集成能力矩阵](INTEGRATIONS.md)。

### 开始使用

- [快速开始 / CLI](#quick-start)
- [GUI 课程与可搜索手册](GUI_RESEARCH_COURSES.md)
- [开发约定](DEVELOPMENT.md)
- [路线图](ROADMAP.md)

### 概念

- [架构](ARCHITECTURE.md)
- [研究正确性与数据限制](RESEARCH_METHODOLOGY.md)
- [集成能力矩阵](INTEGRATIONS.md)

### API

- [因子：注册与验证器](FACTOR_API.md)
- [策略：决策与目标](STRATEGY_API.md)
- [MCP：访问与调用凭证](AGENT_API.md)
- [执行：模拟与 UNKNOWN](EXECUTION.md)
- [券商映射与 mock](BROKER_API.md)

### 验证

- [验证与既有发行限制](RELEASE_PROCESS.md)
- [Python 3.12 发行基础 CI](https://github.com/Siyuan-chat/KabuForge/actions/workflows/kabuforge.yml)
- [发行流程](RELEASE_PROCESS.md)
- [未发布源码候选与版本来源](https://kabuforge.com/)

### 参与开发

- [贡献与许可](CONTRIBUTING.md)
- [安全](SECURITY.md)
- [变更记录](CHANGELOG.md)
- [路线图](ROADMAP.md)

<!-- section:evidence -->
## 证据

源码级参考运行覆盖本地缓存、指标、因子／模型／引擎、历史 Paper、券商预览和敏感性分析，详见[课程](GUI_RESEARCH_COURSES.md)与[能力矩阵](INTEGRATIONS.md)；公开 GUI/worker 路径和 14 条 CLI/MCP 研究路由也已完成源码级验证。干净 wheel 与隔离环境安装工作流的验收凭证单独跟踪，源码运行及截图本身不构成已安装发行包的认证。券商映射为离线操作；显式发起的只读诊断是单独流程，两者都不能证明真实终端已连接。提交与撤销订单保持禁用。

`kabuforge doctor` 报告当前源码/安装分发的版本与本地能力。[首页](https://kabuforge.com/)版本信息从项目版本源生成。[发行页](https://github.com/Siyuan-chat/KabuForge/releases)用于查看历史公开发行。

[English](../en_US/README.md) · [简体中文](../zh_CN/README.md) · [日本語](../ja_JP/README.md)
