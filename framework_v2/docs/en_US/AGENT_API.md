---
doc_id: agent_api
version: 1
locale: en_US
---

# Agent API

<!-- section:contract -->
## Contract

The stdio MCP server starts in an explicitly bounded workspace. It exposes the existing agent tools plus 14 fixed local research operations through the shared `ResearchApplicationService`. The tools have closed JSON schemas and accept explicit workspace file references and fixed recipes. They do not accept user code, imports, shell commands, or interpreter paths. Research results are RESEARCH-ONLY with `pit_guarantee=false`.

R0 tools inspect capabilities, catalogs, registered files/runs/jobs, resources, and an explicitly named historical research-Paper account. They are read-only. R1 performs local validation, analysis, planning, factor/model/engine/indicator research, report sensitivity, broker preview, and explicitly requested broker read-only diagnostics. R1 may write task artifacts under the selected workspace, but it does not submit orders. R2 mutations require the server option `--enable-paper` and both `agent_call_id` and `idempotency_key`. Historical research-Paper creation, step, and run-all additionally require call-level `confirm_paper=true`; workspace drafts do not. R3 order submission/cancellation tools remain reserved and disabled; they are not in the enabled catalog.

Every input path must resolve inside the configured workspace. Calls validate their exact JSON schema and write durable receipts. Research tasks retain stage/status, input and source identities, logs, and a completion or failure receipt. When a task directory was created, failure evidence returns a workspace-relative `task_ref`; retain it for diagnosis rather than deleting or recreating the task. The task reference is not an arbitrary filesystem path.

```shell
kabuforge doctor
kabuforge demo --out output/agent_demo
kabuforge mcp --workspace output/agent_workspace
```

`kabuforge demo` creates fictional synthetic engineering fixtures only; it is not the real local-cache course or market evidence. The MCP process begins without loading broker credentials or contacting a broker.

<!-- section:risk -->
## Risk levels and explicit actions

| Level | Behavior | Gate |
|---|---|---|
| R0 | Read-only inspection, capabilities, catalogs, resources, status and historical Paper query. | No mutation or cursor advance. |
| R1 | Local research tasks and planning; offline broker mapping; explicitly requested localhost read-only diagnostics. | Bounded workspace and explicit input references. Read-only broker GETs require `confirm_read_only=true`; no GET is sent when the reference/configuration is missing or invalid. |
| R2 | Draft mutations and isolated historical Paper account changes. | Server `--enable-paper` and nonempty `agent_call_id` plus `idempotency_key`; historical Paper create/step/run-all also require call `confirm_paper=true`. |
| R3 | External order submit/cancel. | Reserved and disabled; no callable tool is enabled. |

The offline broker mapping preview uses a no-call transport and does not resolve a credential reference. The separate read-only operation resolves only a configured reference when explicitly invoked, then sends bounded GET requests for cash, positions, and orders to the configured localhost API. A missing environment-backed reference fails before transport activity, sends zero GET requests, and is reported without revealing secret values. This proves neither a real broker terminal nor order-book connectivity. The interface cannot submit or cancel orders.

Historical Paper is a new isolated research account created from an explicitly selected frozen bars manifest and a completed strategy report bound by its expected SHA-256. It owns a separate append-only research journal; it never opens the legacy execution ledger. `research_paper_query` is R0 and does not move the cursor or append events. Step/run-all use R2 gates and idempotency. A repeated call with the same identity returns the prior outcome rather than duplicating journal events. The replay uses historical observations and continuous-share research assumptions; it is neither forward Paper nor proof of historical point-in-time availability.

```shell
kabuforge mcp --workspace output/agent_workspace --enable-paper
```

<!-- section:evidence -->
## Evidence and limits

The transport implements JSON-RPC 2.0 `initialize`, `ping`, tools/resources listing, and resource reads. Read-only resources include capabilities, factor and strategy catalogs, schemas, run reports, and selected localized documents. R0/R1 tasks are not trading authorization. R2 Paper opt-in does not enable R3. R3 stays absent even if reserved external hooks are described in metadata.

Call identifiers and idempotency keys are durable protocol inputs, not a substitute for checking a prior uncertain result. If a response is uncertain, inspect the same call/task receipt and reuse the same identity; do not retry a mutation under a new key. Credentials are references only: never place secret values in tool arguments, recipes, task logs, or receipts.

The checked-in `kabuforge demo` path uses fictional fixtures. Formal local-cache courses use explicit user-owned real historical data and have separate source receipts; they do not make those bars or complete reports part of this package. Historical outputs remain RESEARCH-ONLY/PIT false. Live terminal connectivity, approval workflow, order submission, and cancellation are not established.
