---
doc_id: broker_api
version: 1
locale: en_US
---

# Broker API

<!-- section:contract -->
## Contract

Broker mappings and Excel bridge contracts are protocol-level adapters, not enabled trading transports. Broker capabilities can be inspected. The application decision service and agent default catalog have no external submit action.

`--expose-reserved-external` exposes only disabled R3 stubs: `request_order_approval`, `submit_order`, and `cancel_order`. It does not enable them, connect a broker, or grant authority. It preserves the extension surface for a future real-trading MCP integration informed by the Alpaca MCP server reference.

<!-- section:evidence -->
## Evidence

An R3 implementation must supply a trusted broker transport, a human approval authority, single-use approval bound to action/account/plan/order/expiry, and a durable submission journal. The agent cannot mint an approval token. `ReservedExternalActions.execute` always returns `KF_AGENT_DISABLED` today.
