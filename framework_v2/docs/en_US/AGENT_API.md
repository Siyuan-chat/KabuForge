---
doc_id: agent_api
version: 1
locale: en_US
---

# Agent API

<!-- section:contract -->
## Contract

The stdio MCP server starts with a bounded workspace. R0 tools are read-only and available by default; R1 local validation, analysis, planning, demo, backtest, comparison, and cancellation tools are also available by default. R2 workspace drafts and paper simulation tools require `--enable-paper` and require both `agent_call_id` and `idempotency_key`. R3 is not registered by default.

Use `get_capabilities`, factor and strategy catalogs, run inspection, and `kabuforge://` resources to obtain evidence. Calls validate their exact JSON schema, reject paths outside the workspace, and persist a call receipt. Do not retry an uncertain R2 mutation under a new identity.

```shell
kabuforge mcp --workspace output/agent_workspace
kabuforge mcp --workspace output/agent_workspace --enable-paper
```

<!-- section:evidence -->
## Evidence

The transport implements JSON-RPC 2.0 `initialize`, `ping`, tools and resources listing/reading. Resources include capabilities, factor and strategy catalogs, factor/strategy/run schemas, run reports, and localized selected documents. Per-process jobs run in daemon threads and persist job JSON under `agent_jobs`.
