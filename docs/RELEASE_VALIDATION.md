# KabuForge public distribution — validation record

## Current verification — 2026-10-17

Validated on Windows with stock CPython 3.12 against source commit
`9427b4d4e3d512d9aec7d46f443a704d8ec24e0f`. This is software verification
with synthetic, offline and mocked inputs. Public and private distributions
have separate acceptance evidence; private implementation and experimental
runtime results are not included in these public results.

| Check | Actual result |
| --- | --- |
| Public core `unittest` discovery | 420 passed; 0 skipped |
| Top-level `pytest` | 14 passed; 1 existing warning |
| Version tests and version synchronization | 4 tests passed; synchronization passed |
| Public source boundary, documentation and agent catalog | Passed |
| CLI doctor, demo, strategies and canonical recipes | Passed; external actions disabled; research-only recipes retain `pit_guarantee=false` |
| Optional workflows with supported provider versions | analytics: 10 passed, indicators: 9 passed, models: 6 passed, backends: 6 passed; 0 skips |
| Wheel and source distribution | Built; both distribution audits passed |
| Installed wheel | Doctor, demo and installed-package/GUI-resource smoke checks passed |
| Source distribution tutorial | Original installed tutorial check passed |

Build and installation checks reused explicitly selected local dependencies:
the build used `--no-isolation`, and the task-local wheel installation used
`--no-deps`. They do not establish fresh dependency resolution. No package
was published. Existing GitHub checks for the tested source commit passed;
checks for subsequent commits must be evaluated against their own commit IDs.

The initial optional-workflow attempts failed because providers were absent.
Those failures were retained separately. All four original workflows then
passed in a task-local environment using existing installed providers, with
actual dependency versions checked against the declared extra requirements
(including NumPy 2.2.6 and Plotly 6.9.0). This is not a fresh dependency install.

### Boundaries

This verification does not establish real market-data connectivity or
entitlement, investment performance, live broker submission/cancellation,
Excel COM, credential persistence, or an unrestricted compatibility matrix.
Financial/PIT provenance, mutable isolation, dynamic callbacks, task/store
durability and authorization remain governed by the existing contracts and
tests. No CI gate, timeout or test assertion was changed.

The separate private performance investigation is closed under owner-accepted
research criteria. Its measured runtime is not the public package's default
runtime. This closure does not approve CI migration or relabel a historical
performance test failure as a pass.

## Historical verification — 2026-10-01

Validated on 2026-10-01 (Asia/Tokyo), Windows, CPython 3.12, PySide6 6.11.2, with the pinned GUI dependency environment. All checks below ran from this public repository checkout. No private factor modules, production accounts or market-data caches were supplied.

| Check | Actual result |
| --- | --- |
| `python -B -m unittest discover -s framework_v2/tests -q` | 132 existing tests passed |
| `python -B -m unittest framework_v2.tests.test_public_distribution -q` | 2 additional distribution tests passed |
| `python -B -m pytest tests -q` | 14 legacy tests passed; 2 existing `ast.Num` deprecation warnings |
| `python -B -m framework_v2.cli demo --out output/demo` | 5 intents; backtest/paper/fake intent parity true; submitted false |
| `python -B -m framework_v2.cli validate output/demo/backtest.json` | Valid; 6 configuration files |
| `python -B -m framework_v2.cli history output/demo/backtest.json --timeline output/demo/timeline.json --out output/history` | 1 rebalance decision, 3 NAV rows; external submission false |
| `python -B -m framework_v2.capture_acceptance --output <new temporary directory>` | 32 recorded operations and 22 Qt screenshots; completed successfully |

The two distribution tests were added after the first full-suite discovery, so they were run separately. A new full discovery includes all 134 v2 tests. Combined with the 14 legacy tests, 148 distinct tests passed.

## What was verified

- All seven installed implementations have `public.*` identities and resolve to files inside this repository's `factors/` directory.
- A request to construct the built-in registry with `family="private"` is rejected.
- Public 12-1 momentum has the distinct `public.momentum_12_1` identity. The original public factor source files were retained without changing their algorithms.
- Existing tests cover future-row perturbations, financial data conversion, snapshot changes, aliases, planner constraints, idempotency, transaction failures, reconciliation, mocked downloads, and Qt workflows.
- GUI acceptance exercised Chinese/Japanese/English pages, guided strategy creation, synthetic history, local paper simulation, ledger query, manual search, and mocked download-to-price-research behavior.
- The newly generated acceptance screenshots were visually inspected and retained locally. At the user's request, published demonstration media reuse the existing trilingual recordings; their historical research displays are not results of the current public factor distribution. Published GIF/PNG bytes are unchanged and listed in docs/demos/media_manifest.json.

## Retried checks and limits

The first GUI capture run on the workspace drive exceeded the capture script's 120-second worker timeout. Its failed output was retained locally; the task-owned capture process was stopped. The unchanged code completed acceptance in a new temporary directory. An older Python environment's legacy-test attempt was interrupted; the complete 14-test legacy suite then passed in the GUI validation environment.

This is software verification with synthetic/mock inputs. It does not certify investment performance, historical data vintages, real J-Quants connectivity or entitlement, Windows credential persistence, native mouse automation, Excel COM, or live broker integration. The GitHub workflow performs future CI checks independently; the results above are local pre-publication checks.

Generated demo files embed implementation and dependency hashes. Regenerate them in the installed environment instead of copying a prior machine's generated configs. Production data, credentials, private strategies, ledgers, local validation logs and generated workspace directories are excluded from publication.
