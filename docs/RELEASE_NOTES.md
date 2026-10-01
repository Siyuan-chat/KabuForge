# KabuForge v0.1.0-rc.1

`v0.1.0-rc.1` is a public release candidate for the `kabuforge` Python package. It is intended for review of local Japanese-equity research and simulation workflows before a stable public release.

## Public-source split

This release separates the public distribution from the private development source. It includes seven independently published `public.*` factor implementations and does not carry private factor implementations, private parameters, market records, account records, or credentials. Public factors are explicit implementations; they are not asserted to reproduce any omitted private implementation.

## New public interfaces

- `kabuforge` CLI for `doctor`, factor and strategy catalogs, synthetic demo, local backtest/paper simulation, and stdio MCP startup.
- Shared application services with explicit factor and strategy registries, including the registered `composite_factor` strategy implementation.
- Workspace-bounded MCP tools with schema validation, durable local call receipts, R0/R1 default access, and explicit R2 paper opt-in with call and idempotency identities.
- Localized API documentation for Agent, factors, strategies, execution, security, and research-methodology boundaries.

## Trading and research boundaries

The release does not enable real order submission, cancellation, broker connectivity, or trading authority. `--expose-reserved-external` only exposes disabled R3 future-contract stubs. Any later real-trading integration requires a trusted broker transport, human approval authority, single-use action-bound approval, and durable submission/reconciliation evidence.

The available-at lookahead check is a visibility gate, not a complete point-in-time certification. It does not establish data provenance, vendor timing, revisions, survivorship, corporate actions, universe validity, performance, or investment suitability.

## Validation status

Local validation: 158 framework tests and 14 legacy-interface tests passed; 13 focused GUI tests passed after making the installed workbench self-contained. Source, wheel and sdist boundary audits passed. The retained public factor-composite source emits one ast.Num deprecation warning.

Before publishing release assets, a clean wheel installation must pass CLI/MCP/GUI checks, and GitHub Windows/Ubuntu CI for the release revision must pass. See the release validation asset and GitHub Actions for final evidence. No live-broker or strategy certification is claimed.
