---
doc_id: roadmap
version: 1
locale: en_US
---

# Roadmap

<!-- section:contract -->
## Contract

This roadmap separates source-verified research workflows, distribution evidence, and longer-term research readiness. The public source GUI/worker workflows and 14 CLI/MCP research routes have been exercised alongside independently checked local research runs. Version `0.2.0rc1` is an unpublished source candidate. Any distribution acceptance claim is bound to the exact wheel filename, SHA-256, version, Python/platform, installed module origins, and operation-specific checks recorded for that installed artifact; source receipts and screenshots do not substitute for installed-wheel evidence.

### Current engineering stage

- Maintain the five source-verified research flows from explicit user-owned local files: market-data import and identity, indicators, factor evaluation, model/strategy/engine comparison, and historical Paper replay. Their public GUI/worker and CLI/MCP routes have source-level checks. Keep broker mapping and explicit read-only diagnostics separate from order submission.
- For each distribution acceptance claim, verify the selected operations in an isolated install of the identified wheel and retain the matching artifact and runtime receipts. Check optional dependencies per selected operation; metadata or a capability registry alone does not prove an installed worker launched or produced a valid result.
- Preserve source hashes, recipes, input selection identity, worker logs, and failure receipts. Do not bundle the owner's raw market cache, complete reports, model artifacts, or Paper ledger.
- Keep every historical workflow RESEARCH-ONLY with `pit_guarantee=false`; the replayed window is already observed history, not fresh out-of-sample evidence or forward Paper.

### Follow-up research and ecosystem stage (v0.3+)

- Improve strict point-in-time data support with trustworthy historical availability, revision, survivorship, exchange-calendar, corporate-action, and dividend treatment. Do not claim these from download dates or price-only benchmarks.
- Evaluate realistic capacity, liquidity, fees, slippage, market impact, and fresh forward-paper observation before considering any readiness upgrade.
- Expand engine and broker integrations only with explicit capability gates, reproducible evidence, and separate review. Real terminal connectivity remains unverified; live submission and cancellation remain disabled.
- Keep the private Regime state-machine bridge out of the public build unless it is separately migrated and reviewed. Public Regime defaults Off.

These milestones are bounded follow-up work; they do not imply that a future v1 includes every planned research or execution capability.

Any R3 trading extension is contingent on a trusted broker integration, human approval authority, action-bound one-time approvals, durable submission/reconciliation journal, and an explicit separate authorization. It is not implied by an R3 schema or this roadmap.

<!-- section:evidence -->
## Evidence

The public [integration matrix](INTEGRATIONS.md) distinguishes source implementation, discovery, source-run evidence, public GUI/package acceptance, and terminal verification. Its accepted reference runs use three Japanese securities over 1,464 observed dates; all data remain user-supplied and are not packaged. See the [five GUI research courses](GUI_RESEARCH_COURSES.md) for limits and reproduction steps.

The prior release's R3 status remains unchanged: R3 is absent from the default MCP catalog and disabled even when reserved stubs are exposed. Current asynchronous agent work is an in-process daemon-thread model with fail-closed interruption handling.
