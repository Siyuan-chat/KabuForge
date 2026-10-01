---
doc_id: adr_agent_boundary
version: 1
locale: en_US
---

# Agent application boundary

<!-- section:contract -->
## Decision

Agents operate shared application services through validated commands and workspace-bound resources. No arbitrary Python imports, filesystem traversal or broker credentials are accepted. Default MCP registers R0/R1. R2 requires explicit paper opt-in and durable idempotency receipts. R3 hooks remain disabled until a trusted approval authority and broker transport exist.

<!-- section:evidence -->
## Consequences

Disabled R3 schemas can be exposed for integration planning. A displayed schema cannot authorize an order. Reference order surface: [Alpaca official MCP](https://github.com/alpacahq/alpaca-mcp-server). Scientific readiness and live broker certification remain separate acceptance gates.
