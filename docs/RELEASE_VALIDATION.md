# KabuForge public distribution — validation record

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
