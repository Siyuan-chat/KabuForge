---
doc_id: architecture
version: 1
locale: zh_CN
---

# 架构

<!-- section:contract -->
## 合约

`ApplicationService` 是决策边界：它解析已校验配置，使用内存白名单因子与策略注册表，分离研究价格和执行报价，并返回不可变计划。它不能提交订单、写入账本或联络券商。策略配置只能选择已注册实现标识，不能动态导入代码。

Agent 门面增加工作区边界、JSON Schema 校验、凭证扫描、持久调用回执及本地 SQLite 审计状态。路径必须位于工作区内，且不得触及 `.git`、`.aws`、`.codex`、secrets、credentials 或审计数据库。

<!-- section:evidence -->
## 证据

默认策略注册表登记 `composite_factor` 版本 `1`。内置因子标识来自本地 `BuiltinFactors`。计划明确绑定时钟、快照哈希、研究价格、报价、标的、账户及券商能力；计划不等同于执行结果。
