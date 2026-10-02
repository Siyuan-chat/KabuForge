---
doc_id: factor_api
version: 1
locale: en_US
---

# Factor API and extension guide

[English](../en_US/FACTOR_API.md) · [简体中文](../zh_CN/FACTOR_API.md) · [日本語](../ja_JP/FACTOR_API.md)

This guide describes the current v1 configuration contract and public Python boundary. Start here to add a factor; continue with the [Strategy API](STRATEGY_API.md) to turn results into portfolio decisions. This is not a promise of compatibility with every future release.

<!-- section:contract -->
## 1. Implement a callable and a validator

```python
from kabuforge.api import FactorContext, FactorResult, FactorSpec


def compute_factor(spec: FactorSpec, context: FactorContext) -> FactorResult:
    ...


def validate_factor(spec: FactorSpec) -> None:
    ...
```

These are interface signatures, not complete implementations. No `BaseFactor` inheritance is required. Trusted application code registers a callable under an implementation ID and version. The parameter validator must raise on an invalid specification; its return value is not used. `ApplicationService.validate()` runs registered validators before a normal planning run, and planning requires a `FactorResult` return value.

A factor calculates observations or signals, not orders. Keep network access, credential handling, filesystem writes and cache management outside the calculation. Registration is a trust boundary, not a Python sandbox: only load code you trust.

## 2. Define a versioned factor configuration

The runnable tutorial writes this exact `factor.json`:

```json
{
  "schema_version": "1.0",
  "id": "price_change",
  "version": "1",
  "kind": "factor",
  "implementation": {
    "id": "example.price_change",
    "version": "1",
    "parameters": {
      "periods": 1
    }
  },
  "data_requirements": [
    {
      "dataset": "prices",
      "fields": [
        "code",
        "date",
        "close"
      ]
    }
  ],
  "lookback": 2,
  "output": {
    "name": "price_change",
    "description": "Synthetic trailing price change",
    "unit": "return"
  }
}
```

| Field | Meaning and current boundary |
| --- | --- |
| `schema_version` | Configuration schema version; currently `"1.0"`. |
| `id`, `version` | Identity and version of this factor configuration. The ID is also the variable used by strategy formulas. |
| `implementation.id`, `implementation.version` | Exact registered algorithm identity. Unknown versions fail rather than fall back. These are distinct from the configuration version. |
| `implementation.parameters` | Algorithm-specific settings. The common schema requires an object; the registered validator supplies semantic checks. |
| `data_requirements` | Declared dataset names and fields. This is not an automatic downloader or a guarantee of field quality. |
| `lookback` | A nonnegative integer with implementation-defined semantics. This example requires `periods + 1` observations, not calendar days. The framework does not automatically trim data to this number. |
| `output` | Output name, description and optional unit. A unit label does not normalize factor values. |
| `metadata` | Optional descriptive metadata; never embed credentials or code-import instructions. |

The common schema is [factor.schema.json](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/schemas/factor.schema.json). It rejects unknown top-level fields. `FactorSpec.from_config()` creates an immutable specification but does **not** replace full JSON-schema validation. For file-backed runs use the registered service's `validate(run_path)`; validate standalone inputs against the schema as well as your parameter validator.

The tutorial's validator requires integer `periods` in 1–252, rejects booleans and extra parameters, and verifies the declared fields and lookback. Its computation returns the last visible close divided by the close N observations earlier, minus one. Insufficient history stays missing; missing sessions are not fabricated.

## 3. Read only the decision-time context

```python
prices = context.read("prices", fields=("code", "date", "close"))
universe = context.universe()
```

Construct `FactorContext` with an explicitly timezone-aware `decision_at`, a mapping of dataset names to DataFrames, and a nonempty `data_snapshot_hash`. Every input row needs a timezone-aware `available_at`. Missing or timezone-naive availability fails closed. Reads filter rows after the requested cutoff; `asof` may move earlier, never later than the decision. Existing calendar columns such as `date`, `asof_date`, `disclosed_date` and `data_end_date` are also checked, while their original values are retained.

`read(..., fields=...)` also returns `available_at`. Each read is a deep copy. `universe()` reads the latest visible global universe snapshot, filters `in_universe == True`, and rejects duplicate codes. That dataset needs `asof_date`, `code`, `in_universe` and `available_at`.

Declared timing is not proof of genuine historical visibility. Ingestion must separately establish availability, revisions, corporate actions and historical universe membership. A download timestamp is not a substitute. Passing a snapshot hash into a context does not verify its bytes by itself; the tutorial verifies file bytes against the validated run before building the context.

## 4. Return `FactorResult`

Supply `minimal` and `detail` DataFrames plus a `summary` mapping. `minimal` requires these six columns:

| Column | Meaning / validation |
| --- | --- |
| `code` | Nonmissing, unique security identity within this result. |
| `factor_name` | Nonmissing output name; new factors can use `spec.id`. |
| `factor_value` | Finite numeric value or explicit missing value. Infinity and invalid numeric text are rejected. |
| `signal_date` | Signal date; populated by the example with the local decision date. |
| `data_end_date` | End of the data used; missing when the example has no history. |
| `rebalance_date` | Legacy-compatible date metadata; not an instruction to schedule an order. |

One result is a cross-section, not a multi-date panel with duplicate codes. Date columns must exist; the constructor allows missing dates and rejects nonmissing unparseable dates. That permissiveness does not certify temporal evidence. Preserve real timestamps and date meanings in your implementation.

The tutorial returns `FactorResult(..., factor_id=spec.id, binding_id=spec.id)`. `factor_id` optionally verifies `factor_name`; `binding_id` links the result to the configured factor ID. The separate binding supports legacy adapters whose `factor_name` must remain unchanged. The built-in strategy validates bindings; custom strategies must preserve equivalent checks. `from_legacy_dict()` / `to_legacy_dict()` support the existing `minimal/detail/summary` representation. Result accessors return copies.

## 5. Register in trusted startup code

```python
from kabuforge.api import ApplicationService
from examples.extension_demo import compute_price_change, validate_price_change

app = ApplicationService()
app.register_factor(
    "example.price_change", "1", compute_price_change, validate_price_change,
)
```

This fragment registers the factor only. The complete tutorial's `build_service()` registers both factor and strategy. Configuration selects approved IDs; it cannot request arbitrary Python imports, `eval`, or unregistered implementations. Duplicate ID/version pairs fail. Registration belongs to this service instance; a separate CLI, GUI or MCP process does not automatically discover this example or reuse its registry.

## 6. Run the complete offline example

From a source checkout with Python 3.12+:

```shell
python -m pip install -e .
python examples/extension_demo.py --out output/extension_demo
python -m unittest discover -s framework_v2/tests -p test_extension_example.py -v
```

Use a new output directory; the script refuses to overwrite an existing one. Omit `--out` to use a temporary directory. [extension_demo.py](https://github.com/Siyuan-chat/KabuForge/blob/main/examples/extension_demo.py) creates factor, strategy, run, snapshot and account JSON files, validates the configuration graph, computes the factor and calls `ApplicationService.plan()`.

The fictional `SYN_A` changes from 100 to 110 and `SYN_B` from 100 to 95. A deliberately future-dated `SYN_B` price is invisible. The strategy requests `SYN_A`; the position cap reduces its raw weight from 1 to 0.5 before order planning. Printed output explicitly says `synthetic: true` and `orders_submitted: false`. There is no execution, fill, ledger write, historical performance evaluation or broker connection.

<!-- section:evidence -->
## 7. Validation, diagnostics and troubleshooting

[Executable tutorial tests](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/tests/test_extension_example.py) cover the application path, CLI invocation, no-overwrite behavior, future-row isolation, bad timestamps, bad parameters, invalid/duplicate prices, missing-history policies, registration failures, result validation and decision-state semantics. The JSON blocks in all three languages are compared against the executable configuration factories to detect drift.

| Symptom | Check |
| --- | --- |
| Unknown implementation | Register the exact ID/version in the service that validates and runs the configuration. |
| Invalid spec / lookback | Run the common schema and implementation-specific validator; do not silently coerce bad settings. |
| Missing `available_at` / timezone | Repair ingestion evidence; do not invent a historical timestamp to pass the gate. |
| Duplicate codes / observations | Establish the intended data grain and revision policy before calculating. |
| Missing factor values | Supply enough visible history or explicitly choose the strategy's `reject` / `drop` policy. |
| Result binding mismatch | Match the configuration ID and `binding_id`; preserve legacy names only through an explicit adapter. |

The factor cache key binds configuration, algorithm identity, snapshot hash, universe identity and decision time. `FactorSpec.cache_key()` computes an identity; it does not read or write a cache. `list_factors`, `describe_factor`, `validate_factor` and `analyze_factor` are agent-facing catalog/validation/diagnostic tools, not methods every factor must implement. Analysis provides coverage, missingness, distribution, ranks, quantiles and maximum data age; it reports `research_readiness: NOT_EVALUATED`, not evidence of predictive value.

Source of truth: [factor contracts](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/factors.py), [application service](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/application.py), [configuration resolver](https://github.com/Siyuan-chat/KabuForge/blob/main/framework_v2/config.py). Continue with [Strategy API](STRATEGY_API.md) and [Research methodology](RESEARCH_METHODOLOGY.md).
