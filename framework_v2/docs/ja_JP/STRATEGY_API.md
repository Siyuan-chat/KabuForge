---
doc_id: strategy_api
version: 1
locale: ja_JP
---

# 戦略 API

<!-- section:contract -->
## 契約

`StrategyRegistry` は `StrategySpec(implementation_id, implementation_version)` を信頼済み factory へ対応付けます。factory は strategy config と factor IDs を受け、`decide` を実装した `Strategy` を返します。未知又は重複 ID は失敗します。`implementation` のない v1 config は `composite_factor` version `1` のみを解決します。

判断コードは因子結果、point-in-time context、strategy state、decision identity を受けて判断を返します。執行制約と注文作成は後段の risk policy と planner が担当します。

<!-- section:evidence -->
## 根拠

`list_strategies` は登録 ID を、`describe_strategy` は許可済み選択を返します。`plan_strategy` は plan 前に run/execution reference を検証します。catalog は implementation ID と version の順で安定します。
