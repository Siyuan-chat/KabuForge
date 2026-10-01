---
doc_id: agent_api
version: 1
locale: ja_JP
---

# Agent API

<!-- section:contract -->
## 契約

stdio MCP server は制限された workspace で起動します。R0 読取り専用 tools と R1 のローカル検証、分析、plan、demo、backtest、比較、cancel は既定で利用できます。R2 の workspace draft と paper simulation は `--enable-paper` を明示し、`agent_call_id` と `idempotency_key` の両方を要します。R3 は既定で登録されません。

`get_capabilities`、因子・戦略 catalog、run inspection、`kabuforge://` resources から根拠を取得します。呼出しは厳密な JSON schema を検証し、workspace 外を拒否し、receipt を保存します。不確実な R2 mutation を新しい ID で再試行してはいけません。

```shell
kabuforge mcp --workspace output/agent_workspace
kabuforge mcp --workspace output/agent_workspace --enable-paper
```

<!-- section:evidence -->
## 根拠

transport は JSON-RPC 2.0 の `initialize`、`ping`、tools/resources の list/read を実装します。resource は capabilities、因子・戦略 catalog、factor/strategy/run schema、run report、選択済み多言語文書を含みます。job は daemon thread で動作し、`agent_jobs` に JSON を保存します。
