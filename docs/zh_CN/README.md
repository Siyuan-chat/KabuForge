---
doc_id: readme
version: 1
locale: zh_CN
---

# KabuForge 文档

<!-- section:contract -->
## 契约

按下列入口阅读。包版本仍为 0.1.0rc1，已发布 v0.1.0 Release 保留 RC 附件。不提供真实交易或完整历史 PIT 认证。


在源码检出目录执行：

```shell
python -m pip install .
kabuforge doctor
kabuforge demo --out output/demo
kabuforge factors
kabuforge strategies
```

### 开始使用

- [快速开始 / CLI](DEVELOPMENT.md)
- [开发约定](DEVELOPMENT.md)

### 概念

- [架构](ARCHITECTURE.md)
- [研究正确性与数据限制](RESEARCH_METHODOLOGY.md)

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

### 参与开发

- [贡献与许可](CONTRIBUTING.md)
- [安全](SECURITY.md)
- [变更记录](CHANGELOG.md)
- [路线图](ROADMAP.md)

<!-- section:evidence -->
## 证据

`kabuforge doctor`, `kabuforge factors`, `kabuforge strategies`, `kabuforge demo` / Python 3.12+.

[English](../en_US/README.md) · [简体中文](../zh_CN/README.md) · [日本語](../ja_JP/README.md)
