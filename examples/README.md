# Examples

## Factor and Strategy extension tutorial

[English guide](../docs/en_US/FACTOR_API.md) · [中文指南](../docs/zh_CN/FACTOR_API.md) · [日本語ガイド](../docs/ja_JP/FACTOR_API.md)

`extension_demo.py` registers a custom factor and a custom strategy through the
public Python API, validates a versioned configuration graph, and runs the real
application decision/risk/planning pipeline with fictional data. It does not
connect to a data vendor or broker, submit orders, simulate fills, or evaluate
investment performance.

Run from a source checkout with Python 3.12+:

```shell
python -m pip install -e .
python examples/extension_demo.py --out output/extension_demo
python -m unittest discover -s framework_v2/tests -p test_extension_example.py -v
```

Use a new output directory: existing directories are never overwritten. Omit
`--out` for a temporary directory. The example creates `factor.json`,
`strategy.json`, `run.json`, `snapshot.json` and `account.json`; its printed
summary distinguishes requested targets, risk-limited targets and planned orders.
Registration is local to this example's service, not automatic CLI/MCP discovery.

完整示例仅使用合成数据，演示因子与策略注册、配置校验、风控和订单规划，不提交订单。请使用新输出目录，或省略 `--out` 使用临时目录。

この例は合成データのみでファクター・戦略登録、設定検証、リスク、注文計画を示し、注文は送信しません。新しい出力先を指定するか、`--out` を省略してください。

## Synthetic cache schema demo

The existing `synthetic_data/` files show expected local cache shapes without
using real JPX or J-Quants data. They are for understanding CSV schemas, local
cache tables and a minimal configuration without API access. They are not a
validated strategy demo, a realistic market sample, or a substitute for the
J-Quants-backed cache workflow. All symbols, prices, dates, sectors and market-cap
values in `synthetic_data/` are fictional.

Files: `synthetic_data/prices.csv`, `synthetic_data/universe.csv`,
`synthetic_data/sector.csv`, `synthetic_data/market_cap.csv`,
`synthetic_data/index_prices.csv`, and `synthetic_config.json`.

`synthetic_config.json` is the legacy schema-oriented companion configuration,
not the extension tutorial's v1 run configuration. For the legacy backtest
workflow, start with `configs/minimal_long_only.example.json` and prepare a proper
local cache using your own licensed data access. For the registered extension
contracts, use `extension_demo.py` and the guides above.
