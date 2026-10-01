---
doc_id: readme
version: 1
locale: ja_JP
---

# KabuForge ローカル版 v0.1.0-rc.1

<!-- section:contract -->
## 契約

KabuForge は日本株のローカル研究・シミュレーション用パッケージです。宣言的な run ファイルを検証し、因子・戦略判断とブローカー非依存の注文意図を作成し、ローカルのバックテスト、ペーパー、FakeBroker シミュレーションを実行します。実注文は送信しません。ローカル checkout を導入して CLI を使います。

```shell
pip install -e .
kabuforge demo --out output/new_demo
kabuforge mcp --workspace output/agent_workspace
```

公開 RC は既存の公開ファクター実装を維持します。非公開ワークスペースの実装、口座状態、キャッシュ、認証情報を配布物に含めません。従来 GUI の説明は既存マニュアルで維持します。

<!-- section:evidence -->
## 根拠

`kabuforge` は `doctor`、`factors`、`strategies`、`demo`、`backtest`、`paper`、`mcp` を提供します。run mode は `backtest` 又は `paper` と一致しなければなりません。現在は `0.1.0rc1` で、正式 v0.1.0 には独立した公開実装とリリース監査が必要です。
