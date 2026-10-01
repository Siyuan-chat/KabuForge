---
doc_id: research_methodology
version: 1
locale: ja_JP
---

# 研究方法論

<!-- section:contract -->
## 契約

研究入力は decision time と snapshot identity を宣言します。`check_point_in_time` と `check_lookahead` は `available_at` で可視性を検査し、decision timestamp より後の row を数え、point-in-time context で gate する必要があります。available timestamp の欠落はこの検査で invalid です。

`check_lookahead` は available-at gate のみです。provenance、vendor timing、historical revision、survivorship、corporate action、universe construction、経済的妥当性の完全な科学認証ではありません。

<!-- section:evidence -->
## 根拠

診断は `decision_at`、dataset ごとの row 数、欠損 timestamp、future/visible rows、validity、`future_rows_require_gate` を返します。因子診断は与えられた結果を記述するだけで、OOS 成績や投資可能性を証明しません。
