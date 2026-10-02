"""Synthetic Factor/Strategy extension tutorial. Plans only; never submits orders.

From a source checkout with ``python -m pip install -e .``:
    python examples/extension_demo.py --out output/extension_demo
The output directory must not exist. Omitting --out uses a temporary directory.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Mapping

import pandas as pd

from kabuforge.api import (
    AccountState, ApplicationService, FactorContext, FactorResult, FactorSpec,
    RunResult, StrategyDecision, StrategySpec, StrategyState, TargetPortfolio,
)
from kabuforge.execution import Instrument, Quote
from kabuforge.factors import FactorContractError
from kabuforge.models import StrategyError
from kabuforge.strategy_registry import CompositeFactorStrategyAdapter

FACTOR_IMPLEMENTATION = "example.price_change"
STRATEGY_IMPLEMENTATION = "example.positive_score"
IMPLEMENTATION_VERSION = "1"
DECISION_AT = "2024-05-01T09:00:00+09:00"
MINIMAL_COLUMNS = [
    "code", "factor_name", "factor_value", "signal_date",
    "data_end_date", "rebalance_date",
]


def factor_config() -> dict[str, Any]:
    return {
        "schema_version": "1.0", "id": "price_change", "version": "1",
        "kind": "factor",
        "implementation": {"id": FACTOR_IMPLEMENTATION, "version": "1",
                           "parameters": {"periods": 1}},
        "data_requirements": [{"dataset": "prices", "fields": ["code", "date", "close"]}],
        "lookback": 2,
        "output": {"name": "price_change", "description": "Synthetic trailing price change",
                   "unit": "return"},
    }


def strategy_config() -> dict[str, Any]:
    return {
        "schema_version": "1.0", "id": "extension_demo", "version": "1",
        "kind": "strategy",
        "implementation": {"id": STRATEGY_IMPLEMENTATION, "version": "1"},
        "universe": {"snapshot": "universe"}, "factors": ["factor.json"],
        "scoring": {"formula": "price_change"},
        "portfolio": {"construction": "equal_weight", "parameters": {
            "top_n": 1, "preprocess": "none", "missing_policy": "reject"}},
        "risk": {"max_position_weight": 0.5, "max_gross_exposure": 1,
                 "turnover_budget": 2, "allow_short": False},
        "rebalance": {"frequency": "daily"},
    }


def run_config() -> dict[str, Any]:
    return {
        "schema_version": "1.0", "id": "extension_demo_run", "version": "1",
        "kind": "run", "strategy": "strategy.json", "data_snapshot": "snapshot.json",
        "clock": {"start": "2024-05-01", "end": "2024-05-01", "timezone": "Asia/Tokyo"},
        "mode": "fake", "fees": {"commission_rate": 0, "minimum_fee": 0},
        "account_ref": "account.json", "output_dir": "output",
    }


def synthetic_snapshot() -> dict[str, Any]:
    return {"format": "snapshot.inline.v1", "datasets": {
        "prices": {"columns": ["code", "date", "close", "available_at"], "rows": [
            ["SYN_A", "2024-04-26", 100, "2024-04-26T15:00:00+09:00"],
            ["SYN_A", "2024-04-30", 110, "2024-04-30T15:00:00+09:00"],
            ["SYN_B", "2024-04-26", 100, "2024-04-26T15:00:00+09:00"],
            ["SYN_B", "2024-04-30", 95, "2024-04-30T15:00:00+09:00"],
            ["SYN_B", "2024-05-02", 1000000, "2024-05-02T15:00:00+09:00"],
        ]},
        "universe": {"columns": ["code", "asof_date", "in_universe", "available_at"],
                     "rows": [
                         ["SYN_A", "2024-04-30", True, "2024-04-30T15:00:00+09:00"],
                         ["SYN_B", "2024-04-30", True, "2024-04-30T15:00:00+09:00"],
                     ]},
    }}


def validate_price_change(spec: FactorSpec) -> None:
    """Implementation-specific checks complement the common JSON schema."""
    if (spec.implementation_id, spec.implementation_version) != (FACTOR_IMPLEMENTATION, "1"):
        raise FactorContractError("unsupported price-change implementation")
    params = spec.config["implementation"]["parameters"]
    if set(params) != {"periods"}:
        raise FactorContractError("price change requires only the periods parameter")
    periods = params["periods"]
    if type(periods) is not int or not 1 <= periods <= 252:
        raise FactorContractError("periods must be an integer between 1 and 252")
    if spec.config["lookback"] != periods + 1:
        raise FactorContractError("lookback must equal periods + 1 observations")
    requirements = spec.config["data_requirements"]
    if (len(requirements) != 1 or requirements[0]["dataset"] != "prices"
            or set(requirements[0]["fields"]) != {"code", "date", "close"}):
        raise FactorContractError("declare prices fields: code, date, close")


def compute_price_change(spec: FactorSpec, context: FactorContext) -> FactorResult:
    """Last visible close / close N observations earlier - 1, per universe code.

    Insufficient observations remain missing; dates are not gap-filled. This
    toy calculation does not handle corporate actions or certify market data.
    """
    validate_price_change(spec)
    periods = spec.config["implementation"]["parameters"]["periods"]
    codes = sorted(context.universe()["code"].astype(str))
    prices = context.read("prices", fields=("code", "date", "close"))
    prices["code"] = prices["code"].astype(str)
    prices = prices.loc[prices["code"].isin(codes)].copy()
    prices["_date"] = pd.to_datetime(prices["date"], utc=True, errors="raise")
    if prices.duplicated(["code", "_date"]).any():
        raise FactorContractError("duplicate price observation for code/date")
    numeric = pd.to_numeric(prices["close"], errors="coerce")
    if (prices["close"].map(lambda value: isinstance(value, bool)).any()
            or not numeric.map(lambda value: pd.notna(value) and math.isfinite(value) and value > 0).all()):
        raise FactorContractError("visible closes must be finite and positive")
    prices["close"] = numeric
    day = context.decision_at.tz_convert("Asia/Tokyo").date().isoformat()
    rows = []
    for code in codes:
        history = prices.loc[prices["code"].eq(code)].sort_values("_date")
        value = float("nan")
        end = None if history.empty else history.iloc[-1]["date"]
        if len(history) >= periods + 1:
            value = float(history.iloc[-1]["close"] / history.iloc[-periods - 1]["close"] - 1)
        rows.append([code, spec.id, value, day, end, day])
    minimal = pd.DataFrame(rows, columns=MINIMAL_COLUMNS)
    return FactorResult(
        minimal, minimal.copy(deep=True),
        {"synthetic": True, "periods": periods, "universe_count": len(codes)},
        factor_id=spec.id, binding_id=spec.id,
    )


class PositiveScoreStrategy:
    """Tutorial extension: delegate validated scoring, request cash if all scores <= 0."""

    def __init__(self, config: Mapping[str, Any], factor_ids: tuple[str, ...]) -> None:
        if config["portfolio"]["parameters"].get("short_count", 0) != 0:
            raise StrategyError("this tutorial strategy is long-only")
        self._base = CompositeFactorStrategyAdapter(config, factor_ids)

    def decide(
        self, *, results: Mapping[str, FactorResult], context: FactorContext,
        state: StrategyState, decision_identity: str, rebalance: bool = True,
    ) -> StrategyDecision:
        decision = self._base.decide(
            results=results, context=context, state=state,
            decision_identity=decision_identity, rebalance=rebalance,
        )
        if decision.target is not None and not any(value > 0 for value in decision.scores.values()):
            return replace(decision, target=TargetPortfolio.from_weights({}))
        return decision


def build_service() -> ApplicationService:
    """Trusted bootstrap; registration is local to this service, not global discovery."""
    app = ApplicationService()
    app.register_factor(FACTOR_IMPLEMENTATION, IMPLEMENTATION_VERSION,
                        compute_price_change, validate_price_change)
    app.strategy_registry.register(
        StrategySpec(STRATEGY_IMPLEMENTATION, IMPLEMENTATION_VERSION), PositiveScoreStrategy,
    )
    return app


def write_example(root: Path) -> Path:
    """Write only synthetic inputs into a new directory; never overwrite files."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    documents = {
        "factor.json": factor_config(), "strategy.json": strategy_config(),
        "run.json": run_config(), "snapshot.json": synthetic_snapshot(),
        "account.json": {"account_id": "synthetic", "revision": "0", "equity": "100000",
                         "available_cash": "100000", "positions": []},
    }
    for name, document in documents.items():
        with (root / name).open("x", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return root


def _read_bound_json(path: Path, expected_hash: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("input changed after validation: " + str(path))
    return json.loads(raw)


def run_example(root: Path) -> RunResult:
    """Validate configuration and call the real application service, without execution."""
    root = Path(root)
    app = build_service()
    resolved = app.validate(root / "run.json")
    snapshot = _read_bound_json(root / "snapshot.json", resolved.data_snapshot_hash)
    frames = {name: pd.DataFrame(item["rows"], columns=item["columns"])
              for name, item in snapshot["datasets"].items()}
    context = FactorContext(decision_at=DECISION_AT, datasets=frames,
                            data_snapshot_hash=resolved.data_snapshot_hash)
    account = AccountState(**_read_bound_json(root / "account.json", resolved.account_hash))
    now = datetime.fromisoformat(DECISION_AT)
    # Known reference marks are read independently of execution quotes.
    visible = context.read("prices").sort_values("date").groupby("code").tail(1)
    marks = {row.code: Decimal(str(row.close)) for row in visible.itertuples()}
    quotes = {code: Quote(code, price, price, now) for code, price in marks.items()}
    instruments = {code: Instrument(code, 100, Decimal("1")) for code in marks}
    return app.plan(resolved, context=context, account=account, research_marks=marks,
                    quotes=quotes, instruments=instruments, now=now)


def summarize(result: RunResult) -> dict[str, Any]:
    def weights(target: TargetPortfolio | None) -> dict[str, str] | None:
        return None if target is None else {code: str(value) for code, value in target.weights().items()}
    return {
        "synthetic": True, "orders_submitted": False,
        "implementation": result.strategy_implementation_id,
        "raw_target": weights(result.decision.target),
        "allowed_target": weights(result.risk.allowed),
        "risk_reasons": list(result.risk.reasons), "planned_order_count": len(result.plan.intents),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="new directory for synthetic inputs")
    args = parser.parse_args()
    if args.out is not None:
        result = run_example(write_example(args.out))
    else:
        with tempfile.TemporaryDirectory(prefix="kabuforge-extension-") as temp:
            result = run_example(write_example(Path(temp) / "demo"))
    print(json.dumps(summarize(result), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
