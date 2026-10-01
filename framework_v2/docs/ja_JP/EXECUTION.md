---
doc_id: execution
version: 1
locale: ja_JP
---

# 執行境界

<!-- section:contract -->
## 契約

planner は許可 target、account state、執行 quote、instrument、capabilities、明示時刻、turnover budget、fee から broker-neutral order intent を作り、非対応 order type/TIF を拒否します。研究価格は既存 position の評価に、執行 quote は取引計画に用い、混同できません。

ローカル simulation は決定的 FakeBroker を使います。paper/backtest はローカル run であり常に `external_submission: false` を返します。workbench の broker mode は実行できません。

<!-- section:evidence -->
## 根拠

ローカル journal の atomic boundary は SQLite commit に限られます。外部状態が不確実なら再試行前に broker reconciliation evidence が必要であり、この package はその照合も実注文再送も行いません。
