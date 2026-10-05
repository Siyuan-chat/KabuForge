---
doc_id: agent_api
version: 1
locale: zh_CN
---

# Agent API

<!-- section:contract -->
## 合约

stdio MCP 服务器在显式限定的工作区中启动。除既有 Agent 工具外，它还通过共享 `ResearchApplicationService` 提供 14 项固定本地研究操作。工具使用封闭 JSON schema，只接受明确的工作区文件引用和固定 recipe，不接受用户代码、动态导入、shell 命令或解释器路径。研究结果均为 RESEARCH-ONLY，`pit_guarantee=false`。

R0 用于只读查询能力、目录、已注册文件／运行／任务、资源和明确选定的历史研究 Paper 账户。R1 执行本地校验、分析、计划、因子／模型／引擎／指标研究、报告敏感性、券商预览和显式请求的券商只读诊断。R1 可在选定工作区写入任务产物，但不会提交订单。R2 修改操作需要启用服务器参数 `--enable-paper`，并提供 `agent_call_id` 与 `idempotency_key`。历史研究 Paper 的创建、单步和完整回放还需要调用参数 `confirm_paper=true`；工作区草稿不需要该调用确认。R3 订单提交／撤销工具仅保留为预留项，处于禁用状态，不注册在可用工具目录中。

所有输入路径都必须解析到配置的工作区之内。每次调用都会校验精确 JSON schema 并保存持久回执。研究任务保留 stage/status、输入与源码身份、日志以及成功或失败回执。若任务目录已创建，失败响应会提供工作区相对 `task_ref` 作为证据；保留该引用用于排查，不要删除并重新创建任务。它不是任意文件系统路径。

```shell
kabuforge doctor
kabuforge demo --out output/agent_demo
kabuforge mcp --workspace output/agent_workspace
```

`kabuforge demo` 只生成虚构合成的工程 fixture，不是本地真实缓存课程或市场证据。MCP 进程启动时不会读取券商凭证，也不会联系券商。

<!-- section:risk -->
## 风险级别与显式操作

| 级别 | 行为 | 门槛 |
|---|---|---|
| R0 | 只读检查、能力、目录、资源、状态和历史研究 Paper 查询。 | 不修改或推进 cursor。 |
| R1 | 本地研究任务与计划、离线券商映射、显式请求的 localhost 只读诊断。 | 必须限定工作区并明确输入引用。只读券商 GET 要求 `confirm_read_only=true`；引用／配置缺失或无效时不会发送 GET。 |
| R2 | 修改草稿和隔离历史研究 Paper 账户。 | 服务器 `--enable-paper` 与非空 `agent_call_id`、`idempotency_key`；历史研究 Paper 的创建／单步／完整回放还需要调用级 `confirm_paper=true`。 |
| R3 | 对外提交／撤销订单。 | 保留但禁用；没有可调用工具。 |

离线券商映射预览使用不发出调用的 transport，不解析凭证引用。独立的只读操作只有在明确调用时才解析已配置引用，再向所配置的 localhost API 发送有界 cash、positions、orders GET。环境变量引用缺失时会在 transport 前失败，GET 数为 0；结果不会泄露 secret 值。这既不能证明真实券商终端已连接，也不能证明订单簿连通。接口不能提交或撤销订单。

历史研究 Paper 是新建的隔离研究账户，输入为明确选定且已冻结的行情 manifest 和由期望 SHA-256 绑定的已完成策略报告。它拥有独立的追加式研究 journal，不打开旧执行账本。`research_paper_query` 属于 R0，只读且不推进 cursor、不追加事件。step/run-all 需要 R2 门槛和幂等身份。相同身份重试会返回已有结果，不会重复写入 journal。该回放使用历史观察与连续股数研究假设，既不是前向 Paper，也不能证明历史时点的数据可用性。

```shell
kabuforge mcp --workspace output/agent_workspace --enable-paper
```

<!-- section:evidence -->
## 证据与限制

传输实现 JSON-RPC 2.0 的 `initialize`、`ping`、工具／资源列举和资源读取。只读资源包括能力、因子与策略目录、schema、运行报告及选定的本地化文档。R0/R1 工具不构成交易授权。R2 Paper opt-in 不会启用 R3。即使 metadata 显示预留外部 hook，R3 仍不在可用 catalog 中。

调用 ID 与幂等键是持久协议输入，不能代替核查先前不确定结果。如果响应状态不确定，应检查同一 call/task 回执并沿用原身份；不要用新 key 重试修改操作。凭证仅允许引用，禁止把 secret 值放入工具参数、recipe、任务日志或回执。

随包的 `kabuforge demo` 使用虚构 fixture。正式本地缓存课程使用用户自有的真实历史数据和独立来源回执，行情与完整报告不会打包。历史输出保持 RESEARCH-ONLY/PIT false。真实终端连接、审批工作流、订单提交和撤销均未得到验证。
