---
doc_id: execution
version: 1
locale: en_US
---

# Execution Boundary

<!-- section:contract -->
## Contract

The planner creates broker-neutral order intents from an allowed target, account state, execution quotes, instruments, capabilities, explicit time, turnover budget, and fees. It rejects unsupported order types and time-in-force values. Research marks value existing positions; execution quotes drive trade planning. These inputs must not be conflated.

Local simulation uses a deterministic fake broker. Paper and backtest modes are local runs and always report `external_submission: false`. A broker mode is not executable from the workbench.

<!-- section:evidence -->
## Evidence

The local journal treats SQLite commit as its atomic boundary only. An uncertain external state would require broker reconciliation before retry; this package does not perform that reconciliation or resend a real order.
