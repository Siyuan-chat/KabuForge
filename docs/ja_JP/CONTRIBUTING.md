---
doc_id: contributing
version: 1
locale: ja_JP
---

# コントリビュート

<!-- section:contract -->
## 契約

貢献は local-first と no-live-trading の境界を維持します。境界を変える場合は validation、registry identity、workspace containment、idempotency、failure state の test を加えます。GUI guidance は既存 manual に残し、package API 文書で書き換えません。

新しい公開因子・戦略には独立実装可能な version、validator、fixture、provenance 説明、情報時点レビューが必要です。private factor code や credential を公開 artifact に含めてはいけません。

<!-- section:evidence -->
## 根拠

review 前に影響を受ける CLI と関連 test を実行し、公開配布の境界を検証します。新実装には review が必要です。出典、認証情報、非公開コードの gate を弱めてはいけません。

プロジェクト所有のコード、文書、資産への新規貢献は AGPL-3.0-only で提出します。第三者通知を保持し、許諾権限のある資料のみを提出してください。追加 CLA は導入しません。
