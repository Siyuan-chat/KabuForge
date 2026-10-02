---
doc_id: strategy_api
version: 1
locale: en_US
---

# Strategy API and extension guide

[English](../en_US/STRATEGY_API.md) · [简体中文](../zh_CN/STRATEGY_API.md) · [日本語](../ja_JP/STRATEGY_API.md)

Read the [Factor API](FACTOR_API.md) first. This guide describes the current registered strategy contract, not a broker execution API. The shared pipeline is Factor → StrategyDecision → TargetPortfolio → RiskPolicy → Planner → OrderIntent.

<!-- section:contract -->
## 1. Implement the registered decision contract

```python
from typing import Mapping, Protocol
from kabuforge.api import FactorContext, FactorResult, StrategyDecision, StrategyState


class Strategy(Protocol):
    def decide(
        self, *, results: Mapping[str, FactorResult], context: FactorContext,
        state: StrategyState, decision_identity: str, rebalance: bool = True,
    ) -> StrategyDecision:
        ...
```

This is the interface signature. A factory receives `(config, factor_ids)` and returns an object with `decide`. It may be a class constructor. Registration is structural; you do not have to inherit a base class. Factories should reject settings they cannot support. Only trusted application code may register them; configuration cannot import arbitrary code.

| Input | Meaning |
| --- | --- |
| `results` | Mapping from configured factor ID to validated `FactorResult`. These keys are not implementation IDs. |
| `context` | Read-only, point-in-time data and current decision time. |
| `state` | Explicit state from the previous decision, or an initial `StrategyState()`. |
| `decision_identity` | Identity of this decision. The built-in adapter rejects reprocessing the last identity; preserve equivalent checks in independent implementations. |
| `rebalance` | Whether to request a new target on this call. Default is `True`. |

**Compatibility trap:** `framework_v2.strategy.CompositeFactorStrategy.decide()` returns `(target, state)`, not the registered result object. Use `CompositeFactorStrategyAdapter`, whose `decide()` calls `decide_with_audit()` and returns `StrategyDecision`. The tutorial uses this adapter to preserve factor binding, date, missingness, formula and duplicate-decision checks.

## 2. Return a full decision, not an order

`StrategyDecision` requires all nine fields:

| Field | Purpose |
| --- | --- |
| `target` | Full `TargetPortfolio`, or `None` for no rebalance. |
| `state` | New `StrategyState`; pass it to the next decision. |
| `scores` | Per-code finite scores. |
| `ranked_codes`, `dropped_codes` | Deterministic ranking and explicitly excluded codes. |
| `preprocess`, `missing_policy` | Description of the policies actually used. |
| `factor_inputs`, `factor_processed` | Raw and transformed per-factor/per-code values for inspection. |

An independent non-scoring strategy may use empty audit mappings where meaningful; it must still populate the contract honestly. Do not fabricate scores or implied evidence. This does not remove the current file schema's scoring requirements.

```python
from kabuforge.api import TargetPortfolio

no_rebalance = None
liquidate_to_cash = TargetPortfolio.from_weights({})
full_target = TargetPortfolio.from_weights({"SYN_A": "0.5"})
```

These three values have different meanings. `None` keeps the current allocation without requesting rebalance. An empty target requests liquidation to cash. A nonempty target is the **entire desired portfolio**, not an incremental buy instruction: previously held codes absent from it are targeted to zero. A liquidation request may be constrained or only partly achievable after risk and planning.

Weights use finite `Decimal` values. `TargetPortfolio.cash_residual` means `1 - long_gross`, not actual account cash and not `1 - net`. Target types can express short weights, but that alone does not establish executable short-selling or live broker support.

`StrategyState` contains `last_decision_identity`, `regime`, `cooldown_until` and JSON-compatible `transition_state`, with `to_json()` / `from_json()` for explicit persistence. State fields do not implement a regime or cooldown algorithm by themselves. The application creates a strategy through its factory for each plan; do not rely on mutable instance state surviving across decisions.

## 3. Define a strategy configuration

The tutorial writes this exact `strategy.json`:

```json
{
  "schema_version": "1.0",
  "id": "extension_demo",
  "version": "1",
  "kind": "strategy",
  "implementation": {
    "id": "example.positive_score",
    "version": "1"
  },
  "universe": {
    "snapshot": "universe"
  },
  "factors": [
    "factor.json"
  ],
  "scoring": {
    "formula": "price_change"
  },
  "portfolio": {
    "construction": "equal_weight",
    "parameters": {
      "top_n": 1,
      "preprocess": "none",
      "missing_policy": "reject"
    }
  },
  "risk": {
    "max_position_weight": 0.5,
    "max_gross_exposure": 1,
    "turnover_budget": 2,
    "allow_short": false
  },
  "rebalance": {
    "frequency": "daily"
  }
}
```

`factors` contains file paths relative to the strategy file. `scoring.formula` references the **IDs inside those factor configurations**; here `price_change`, not `factor.json` or `example.price_change`. The resolver checks the complete run → strategy → factors graph and content identities before planning.

`implementation` chooses a registered strategy. Omitting it from a v1 configuration selects only `composite_factor` version `"1"`; the configuration's own `version` does not select an algorithm version. The current application planning path requires `universe: {"snapshot": "universe"}` even though the schema also describes a path form.

### Built-in composite behavior

The adapter supports arithmetic using factor IDs, finite constants, `+`, `-`, `*`, `/` and unary signs; no function calls, attributes, indexing or arbitrary evaluation. Preprocessing is `none`, `zscore` or `rank`; missing values are explicitly `reject` or `drop`. Eligible codes are the universe intersection with nonmissing values for every referenced factor. Ties are broken by code.

It selects top-ranked longs and bottom-ranked remaining shorts, with equal weights within each side and explicit gross allocations. `portfolio.construction: "rank"` is currently an alias for the equal-weight construction, **not rank-proportional weighting**. Short targets remain subject to downstream execution limits.

### Current extension limits

Selecting a custom factory does not create a custom configuration schema. [strategy.schema.json](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/schemas/strategy.schema.json) still requires factors, a scoring formula, portfolio, risk and rebalance fields, and restricts portfolio parameter names. The resolver still checks the formula. A factor-free event strategy or a new optimizer parameter block requires an explicit future schema/integration change, not undocumented JSON fields.

The schema recognizes daily, weekly and monthly rebalance settings. `ApplicationService.plan()` itself does not evaluate that calendar and calls `decide` with its default `rebalance=True`; a declared frequency is not proof that the caller enforces it. Put actual scheduling in the appropriate caller or explicitly implemented strategy logic and test that path.

## 4. Register a trusted factory

```python
from kabuforge.api import ApplicationService, StrategyRegistry, StrategySpec
from examples.extension_demo import PositiveScoreStrategy

registry = StrategyRegistry()
registry.register(
    StrategySpec("example.positive_score", "1"), PositiveScoreStrategy,
)
app = ApplicationService(strategy_registry=registry)
```

This registers the strategy only. Register required factors on the same application service before validating a run; `examples/extension_demo.py:build_service()` shows both registrations. Unknown and duplicate identities fail; the catalog sorts by implementation ID and version. Registration is in memory, local to the service. It does not install a package entry point or make a separate CLI/GUI/MCP process automatically load the extension. Integrate the same trusted bootstrap into any frontend that should use it.

The sample `PositiveScoreStrategy` delegates scoring to the adapter, then requests an empty cash target if no processed score is positive. It preserves the audit and new state with `dataclasses.replace`. On a no-rebalance call it keeps `target=None`. It rejects short selection; this is a teaching policy, not a validated investment strategy.

## 5. Connect a run and the planning boundary

The tutorial's `run.json` is:

```json
{
  "schema_version": "1.0",
  "id": "extension_demo_run",
  "version": "1",
  "kind": "run",
  "strategy": "strategy.json",
  "data_snapshot": "snapshot.json",
  "clock": {
    "start": "2024-05-01",
    "end": "2024-05-01",
    "timezone": "Asia/Tokyo"
  },
  "mode": "fake",
  "fees": {
    "commission_rate": 0,
    "minimum_fee": 0
  },
  "account_ref": "account.json",
  "output_dir": "output"
}
```

The generated sibling files include `factor.json`, `strategy.json`, `snapshot.json` and `account.json`. File references are resolved relative to the file that contains each reference. The zero fees, account and prices are synthetic, not realistic execution assumptions.

`app.validate(run_path)` resolves configurations and runs validation. `app.plan(...)` then needs the resolved run, a matching `FactorContext`, `AccountState`, separate research marks and execution quotes, instruments, an explicit timezone-aware `now`, and optionally prior state and capabilities. It returns `RunResult` containing factor results, decision, risk decision and order plan. The service does not submit orders or write an execution ledger.

Research marks belong to the decision snapshot. Execution quotes may constrain the later plan but must not retrospectively select the research target. Risk policy is applied after the strategy, followed by lot-size, price, cash and other planning checks. A successful plan is not a fill.

From a source checkout with Python 3.12+:

```shell
python -m pip install -e .
python examples/extension_demo.py --out output/extension_demo
python -m unittest discover -s framework_v2/tests -p test_extension_example.py -v
```

Use a fresh output directory, or omit `--out` for a temporary one. The example runs one decision and prints the raw/allowed targets, risk reasons and planned order count, together with `orders_submitted: false`. It is not a historical backtest, paper fill or live trade.

<!-- section:evidence -->
## 6. Tests, discovery and troubleshooting

[extension_demo.py](https://github.com/Siyuan-chat/KabuForge/blob/main/examples/extension_demo.py) is the complete implementation. [test_extension_example.py](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/tests/test_extension_example.py) checks the registered application pipeline, CLI, missing-value policies, future inputs/results, no-rebalance versus liquidation, duplicate decisions, state serialization and configuration examples in all three languages. The existing CI discovers this test module without adding a separate test command to workflows.

| Symptom | Check |
| --- | --- |
| Unknown strategy | Register the exact implementation ID/version in the active service. |
| Tuple returned instead of decision | Use the registered adapter contract, not the legacy `decide()` shorthand. |
| Unsupported parameter in JSON | Respect the existing schema; a registry entry is not a schema extension. |
| Duplicate decision | Carry and persist the returned state; do not silently replay the same identity. |
| Unexpected liquidation | Do not substitute an empty target for `None`; they are intentionally different. |
| Requested and allowed targets differ | Inspect `RunResult.risk` and plan reasons rather than rewriting research signals from execution prices. |
| Custom strategy absent in another process | Install its trusted bootstrap in that frontend; registration is not global. |

`list_strategies` and `describe_strategy` expose catalog information; `plan_strategy` validates run and execution references before planning. These are agent tools rather than strategy protocol methods. They do not grant arbitrary code-loading or real-order permissions. Source of truth: [strategy registry](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/strategy_registry.py), [decision models](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/models.py), [built-in strategy and risk](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/strategy.py), [application service](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/application.py). See also [Execution](EXECUTION.md) and [Agent API](AGENT_API.md).
