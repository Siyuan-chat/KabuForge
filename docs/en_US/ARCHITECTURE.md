---
doc_id: architecture
version: 1
locale: en_US
---

# Architecture

<!-- section:contract -->
## Contract

`ApplicationService` is the decision boundary. It resolves validated configurations, uses an allow-listed in-memory factor registry and strategy registry, separates research marks from execution quotes, and returns an immutable plan. It cannot submit, write a ledger, or contact a broker. Strategy configurations select a registered implementation identity; they never dynamically import code.

The agent facade adds a workspace boundary, JSON-schema validation, credential scanning, durable call receipts, and local SQLite audit state. Paths must remain under its workspace and cannot address `.git`, `.aws`, `.codex`, secrets, credentials, or its audit database.

<!-- section:evidence -->
## Evidence

The default strategy registry registers `composite_factor` version `1`. Built-in factor identities come from the local `BuiltinFactors` provider. Planning uses explicit clocks, snapshot hashes, research marks, quotes, instruments, account state, and broker capabilities; a planning result is not an execution result.
