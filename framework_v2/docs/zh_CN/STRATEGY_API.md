---
doc_id: strategy_api
version: 1
locale: zh_CN
---

# 策略 API

<!-- section:contract -->
## 合约

`StrategyRegistry` 将 `StrategySpec(implementation_id, implementation_version)` 映射至可信工厂。工厂接收策略配置和因子 ID，必须返回实现 `decide` 的 `Strategy`。未知或重复标识失败。没有 `implementation` 字段的 v1 配置只解析为 `composite_factor` 版本 `1`。

决策代码接收因子结果、时点上下文、策略状态和决策标识，返回决策；风险政策与规划器随后施加执行约束并构建订单。

<!-- section:evidence -->
## 证据

`list_strategies` 返回登记标识，`describe_strategy` 描述获准选择。`plan_strategy` 先校验运行与执行引用。策略目录按实现 ID、版本稳定排序。
