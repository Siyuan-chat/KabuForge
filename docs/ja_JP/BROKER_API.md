---
doc_id: broker_api
version: 1
locale: ja_JP
---

# ブローカー API

<!-- section:contract -->
## 契約

broker mapping と Excel bridge は protocol-level adapter であり、有効な取引 transport ではありません。broker capability は確認できますが、application service と既定 Agent catalog に外部注文操作はありません。

`--expose-reserved-external` は無効 R3 stub の `request_order_approval`、`submit_order`、`cancel_order` だけを露出します。有効化、broker 接続、権限付与はしません。これは Alpaca MCP server を参考にした将来の実取引 MCP の extension surface を保持するものです。

<!-- section:evidence -->
## 根拠

R3 実装には trusted broker transport、human approval authority、action/account/plan/order/expiry に束縛された一回限り approval、durable submission journal が必要です。Agent は approval token を mint できません。現在 `ReservedExternalActions.execute` は必ず `KF_AGENT_DISABLED` を返します。
