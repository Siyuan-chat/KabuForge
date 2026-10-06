# Entry point audit — 2026-10-06

| Entry | Disposition | Evidence |
| --- | --- | --- |
| `kabuforge` | Current CLI / MCP | `pyproject.toml`; `src/kabuforge/cli.py` |
| `Launch_KabuForge.bat` | Current Windows launcher | `framework_v2/launch_kabuforge.ps1` starts `framework_v2.workbench_qt` |
| `framework_v2` | Current package; retain | Declared package, used by `src/kabuforge/application.py` |
| `gui_app`, `OPEN_BACKTEST_GUI.bat`, `Install_GUI_Dependencies.bat`, `start_here.bat` | Compatibility chain | Old launcher → `runtime/run_gui.py` → `gui_app.main`; installer selects Python 3.10 |
| `LOCAL_BACKTEST_RUNNER.md` | Compatibility docs | Documents `runtime/run_backtest.py`, used by `gui_app/adapters/backtest_adapter.py` |
| `runtime` | Mixed current data helpers and compatibility; retain | `framework_v2/legacy_provider.py` and `prepare_legacy_research.py` use data helpers |

No bulk move is applied. The old GUI remains referenced by
`tests/test_formula_validation.py`, `runtime/run_gui.py` and
`runtime/Launch_Backtest_GUI.pyw`. A later small compatibility migration must
update this chain together, tests, imports and source/build manifests; retain
forwarding launchers where promised and pass distribution checks. Confirm removal
policy before deleting it. Current runtime data helpers and framework stay packaged.
