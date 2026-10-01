---
doc_id: readme
version: 1
locale: en_US
---

# KabuForge v0.1.0-rc.1

<!-- section:contract -->
## Contract

KabuForge is a local Japanese-equity research and simulation package. It validates declarative run files, builds factor and strategy decisions, plans broker-neutral intents, and runs local backtest, paper, or fake-broker simulations. It does not submit a real order. Install the local checkout and use the public CLI:

```shell
pip install -e .
kabuforge demo --out output/new_demo
kabuforge mcp --workspace output/agent_workspace
```

The public RC retains the already-published public factor implementations. Private workspace implementations, account state, caches and credentials are excluded from this distribution. Legacy GUI instructions remain available in the existing manuals.

<!-- section:evidence -->
## Evidence

`kabuforge` dispatches `doctor`, `factors`, `strategies`, `demo`, `backtest`, `paper`, and `mcp`. A run mode must match `backtest` or `paper`; `demo` produces local synthetic output. Current release metadata is `0.1.0rc1`; a formal v0.1.0 follows RC feedback and release validation.
