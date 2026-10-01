---
doc_id: factor_api
version: 1
locale: ja_JP
---

# 因子 API

<!-- section:contract -->
## 契約

因子は implementation ID と version により allow-list registry から選択されます。実装は `FactorSpec` と `FactorContext` を受け取り `FactorResult` を返し、登録 validator が事前に仕様を検査します。動的 import、eval、未検証実装の選択は禁止です。

cache key は実装 parameter、data snapshot hash、universe identity、decision time を束縛します。そのため cache hit は因子名だけでなく宣言済み研究 context にも束縛されます。

<!-- section:evidence -->
## 根拠

`list_factors`、`describe_factor`、`validate_factor`、`analyze_factor` は catalog、検証、記述統計を提供します。分析は coverage、欠損、分布、rank、quantile、最大 data age と `research_readiness: NOT_EVALUATED` を返します。
