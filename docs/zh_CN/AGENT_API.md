---
doc_id: agent_api
version: 1
locale: zh_CN
---

# Agent API

<!-- section:contract -->
## 合约

stdio MCP 服务器以受限工作区启动。R0 只读工具默认可用；R1 本地校验、分析、计划、演示、回测、比较和取消工具也默认可用。R2 工作区草稿与纸面模拟必须显式传入 `--enable-paper`，并同时提供 `agent_call_id` 与 `idempotency_key`。R3 默认不注册。

使用 `get_capabilities`、因子/策略目录、运行检查和 `kabuforge://` 资源取得证据。调用校验精确 JSON schema、拒绝工作区外路径并持久保存回执；不确定的 R2 修改不得以新身份重试。

```shell
kabuforge mcp --workspace output/agent_workspace
kabuforge mcp --workspace output/agent_workspace --enable-paper
```

<!-- section:evidence -->
## 证据

传输实现 JSON-RPC 2.0 的 `initialize`、`ping`、工具和资源列举/读取。资源包括能力、因子/策略目录、factor/strategy/run schema、运行报告和选定的本地化文档。进程内任务使用 daemon 线程，任务 JSON 保存在 `agent_jobs`。
