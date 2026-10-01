---
doc_id: changelog
version: 1
locale: en_US
---

# Changelog

<!-- section:contract -->
## Contract

## 0.1.0-rc.1

Introduces the local package CLI and bounded MCP adapter, typed factor and strategy registries, local agent audit receipts, R0/R1 default catalog, R2 paper opt-in, and reserved disabled R3 approval/order interfaces. The public RC separates the public package from the private local workspace and pins its public factor sources.

<!-- section:evidence -->
## Evidence

Known limits: no real broker submission through the agent; `--expose-reserved-external` only exposes disabled stubs; job work is an in-process daemon thread; restart converts queued/running jobs to `FAILED` with `KF_JOB_INTERRUPTED`; automatic recovery/replay is unavailable; lookahead checking is timestamp-gate scope only.
