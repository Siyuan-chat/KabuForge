---
doc_id: security
version: 1
locale: en_US
---

# Security

<!-- section:contract -->
## Contract

Agent inputs are schema-validated and checked for credential-like values. Relative paths are resolved under the configured workspace; absolute paths, traversal, symlinks escaping the root, and protected credential/control locations are rejected. JSON input is bounded to 64 MiB for workspace reads and MCP lines to 1 MiB.

R2 mutations require a caller-supplied call ID and idempotency key. R3 remains disabled. Human approval must be supplied by a trusted future host and consumed once; neither an agent tool nor a configuration value may create it.

<!-- section:evidence -->
## Evidence

Call receipts include call ID, idempotency key, input/result hashes, run ID, timestamp, tool, and state in workspace SQLite. Reused idempotency keys return durable prior outcomes or an uncertainty rejection rather than silently repeating a mutation.
