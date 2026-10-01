---
doc_id: broker_api
version: 1
locale: zh_CN
---

# 券商 API

<!-- section:contract -->
## 合约

券商映射和 Excel bridge 是协议级适配器，不是已启用的交易传输。可以检查券商能力；应用决策服务和 Agent 默认目录均无外部下单动作。

`--expose-reserved-external` 只暴露禁用的 R3 stub：`request_order_approval`、`submit_order` 和 `cancel_order`。它不启用它们、不连接券商、不授予权限；该接口为未来参考 Alpaca MCP server 的真实交易 MCP 保留。

<!-- section:evidence -->
## 证据

R3 实现须提供可信券商传输、人工审批权威、与动作/账户/计划/订单/到期绑定的一次性审批、以及持久提交账本。Agent 无法铸造审批令牌。当前 `ReservedExternalActions.execute` 永远返回 `KF_AGENT_DISABLED`。
