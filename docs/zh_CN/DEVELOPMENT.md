---
doc_id: development
version: 1
locale: zh_CN
---

# 开发

<!-- section:contract -->
## 合约

应面向软件包边界开发，不要依赖 GUI 内部或配置驱动导入。以 `ApplicationService.register_factor(id, version, function, validator)` 登记可信因子，以 `StrategyRegistry.register(StrategySpec, factory)` 登记可信策略。校验器必需；重复标识会被拒绝。

使用确定性的本地夹具。研究数据、凭证、券商传输和私有实现不得进入公共发行物。模拟成交、计划意图或 CLI 成功退出都不能证明真实执行。

<!-- section:evidence -->
## 证据

公开包名为 `kabuforge`，要求 Python 3.12+，项目自有材料采用 AGPL-3.0-only，并保留第三方许可通知，入口为 `kabuforge = kabuforge.cli:main`。`public_source_manifest.json` 固定公开源码身份，并检查源码、wheel 和 sdist。
