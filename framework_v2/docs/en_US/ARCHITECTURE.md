---
doc_id: architecture
version: 1
locale: en_US
---

# Architecture

<!-- section:contract -->
## Contract

KabuForge keeps two service layers with different contracts. The existing `ApplicationService` is the legacy decision boundary: it resolves validated configurations, uses allow-listed factor and strategy registries, separates research marks from execution quotes, and returns a plan. It cannot submit, write a ledger, or contact a broker. Strategy configurations select a registered implementation identity; they never dynamically import code. Its `available_at` and execution timeline rules remain intact for callers that use those schemas.

The shared `ResearchApplicationService` is an adapter over fixed local research cores, not a replacement financial engine. It accepts explicit file references and fixed recipe data, checks selected input/source identities, creates workspace-bounded task artifacts, and retains request, launch, result/failure receipts and logs. The facade is available to supported Python and adapter operations; GUI, CLI, and MCP each keep their own allowlists, and not every legacy screen or command is routed through this facade. Adapters do not implement a second calculation path for the fixed cores they invoke. Requests cannot supply code, module imports, shell commands, or interpreter paths. Optional model, indicator, and backend packages are checked for the selected operation and run through static workers where defined, keeping heavyweight imports out of the GUI's main process.

The two input contracts must not be conflated. Legacy snapshots can require explicit `available_at` and visibility checks. Local historical-bar research freezes an explicitly selected CSV/Parquet/snapshot/manifest and records coverage, price basis, source/selection hashes, and assumptions; it does not invent historical availability timestamps. Its results are RESEARCH-ONLY with `pit_guarantee=false`.

The agent facade retains its own workspace boundary, JSON-schema validation, credential scanning, durable call receipts, and local SQLite audit state. Its paths cannot address `.git`, `.aws`, `.codex`, secrets, credentials, or the audit database. Historical Paper research is a separate isolated append-only research replay with explicit opt-in; it is neither the legacy execution ledger nor a live/forward Paper account.

Offline broker order mapping uses a no-call transport and does not resolve a secret. A separately invoked read-only check can resolve an explicitly configured reference and issue cash, positions, and orders GET requests to the configured local endpoint. That path has not verified a real broker terminal. Order submission and cancellation remain disabled. R3 stays absent from the default MCP catalog; exposing reserved stubs does not enable them or grant authority.

<!-- section:evidence -->
## Evidence

The default legacy strategy registry registers `composite_factor` version `1`. Built-in factor identities come from the local `BuiltinFactors` provider. Planning uses explicit clocks, snapshot hashes, research marks, quotes, instruments, account state, and broker capabilities; a planning result is not an execution result.

In the newer research flow, price momentum is the default strategy. Local cache freeze and the factor cache are explicit and identity-bound; factor-cache reuse applies only to factor-strategy operations wired to it, not every legacy data/factor path. Factor feature rows and forward-label evaluation rows are separate artifacts. Fixed LightGBM/CatBoost models use chronological train/validation/historical-test partitions and purged label boundaries. Native, VectorBT, and Backtrader candidates replay fixed orders independently; reported account-path agreement does not imply identical fill streams for every input.

TA-Lib and native `pandas-ta` are the two indicator providers. Selected optional runtimes are checked by a static worker gate, not by importing every optional library in the main GUI. The report dashboard uses a dark 19-figure layout (15 summary figures, 3 per-security price/execution figures, 1 Regime panel) and a separate fixed fee/delay sensitivity panel. TOPIX is a price index without dividends and is joined only on exact NAV dates. The archived reference report's Regime panel is Off/unavailable with zero traces; the public build defaults Regime Off and excludes the private state-machine bridge. The bundled offline help has 24 searchable chapters, including the three-language research courses.

The source candidate is version `0.2.0rc1`, unpublished. Public GUI/worker workflows and the Python, CLI, and MCP research routes have been validated against source. Any distribution acceptance statement must identify the exact wheel filename, SHA-256, version, Python/platform, and installed module origins, then record operation-specific checks against that installed artifact; source screenshots and source tests are not installed-wheel evidence. Data in examples is user-supplied and is not packaged. Current historical reports remain RESEARCH-ONLY/PIT false, not strict PIT, fresh OOS, PAPER-READY, or live-execution evidence.
