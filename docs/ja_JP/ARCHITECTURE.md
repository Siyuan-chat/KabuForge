---
doc_id: architecture
version: 1
locale: ja_JP
---

# アーキテクチャ

<!-- section:contract -->
## 契約

`ApplicationService` は判断境界です。検証済み設定を解決し、メモリ上の allow-list 因子・戦略 registry を使い、研究価格と執行 quote を分離して不変 plan を返します。注文送信、ledger 書込み、ブローカー接続はできません。戦略設定は登録済み実装 ID だけを選び、動的 import はしません。

Agent facade は workspace 境界、JSON Schema 検証、認証情報走査、永続 call receipt、ローカル SQLite 監査状態を追加します。パスは workspace 内に限られ、`.git`、`.aws`、`.codex`、secrets、credentials、監査 DB を参照できません。

<!-- section:evidence -->
## 根拠

既定 registry は `composite_factor` version `1` を登録します。組込み因子 ID はローカル `BuiltinFactors` 由来です。plan は clock、snapshot hash、研究価格、quote、銘柄、account、broker capabilities に明示的に束縛され、執行結果ではありません。
