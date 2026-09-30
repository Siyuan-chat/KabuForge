"""Synthetic PIT and legacy-boundary tests; no private data or broker calls."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from framework_v2.factors import FactorContext, FactorContractError, FactorResult, FactorSpec
from framework_v2.legacy_factors import LegacyFactorAdapter, LegacyFactorRegistry


DECISION = "2025-01-07T10:00:00+09:00"
KNOWN = "2025-01-07T09:00:00+09:00"
FUTURE = "2025-01-07T15:00:00+09:00"


def spec(*, factor_id: str = "quality", impl_id: str = "private.quality",
         impl_version: str = "1", parameter: int = 1) -> FactorSpec:
    return FactorSpec.from_config({
        "schema_version": "1.0", "kind": "factor", "id": factor_id, "version": "1",
        "implementation": {"id": impl_id, "version": impl_version,
                           "parameters": {"window": parameter}},
        "data_requirements": [{"dataset": "prices", "fields": ["close"]}],
        "lookback": 1, "output": {"name": "score", "description": "test"},
    })


def tables() -> dict[str, pd.DataFrame]:
    return {
        "prices": pd.DataFrame([
            {"date": "2025-01-06", "code": "1001", "close": 10.0, "available_at": KNOWN,
             "metadata": {"tags": ["original"]}},
            {"date": "2025-01-07", "code": "1001", "close": 20.0, "available_at": FUTURE,
             "metadata": {"tags": ["future"]}},
        ]),
        "financial_summary": pd.DataFrame([
            {"disclosed_date": "2025-01-06", "code": "1001", "profit": 1.0, "available_at": KNOWN},
            {"disclosed_date": "2025-01-07", "code": "1001", "profit": 999.0, "available_at": FUTURE},
        ]),
        "universe": pd.DataFrame([
            {"asof_date": "2025-01-06", "code": "1001", "in_universe": True, "available_at": KNOWN},
            {"asof_date": "2025-01-07", "code": "2002", "in_universe": True, "available_at": FUTURE},
        ]),
    }


def minimal(*, values: tuple[float, ...] = (1.0,),
            codes: tuple[str, ...] = ("1001",), factor_name: str = "quality") -> pd.DataFrame:
    return pd.DataFrame({
        "code": codes, "factor_name": factor_name, "factor_value": values,
        "signal_date": ["2025-01-06"] * len(codes),
        "data_end_date": ["2025-01-06"] * len(codes),
        "rebalance_date": ["2025-01-07"] * len(codes),
    })


class FactorTests(unittest.TestCase):
    def context(self, dataset: dict[str, pd.DataFrame] | None = None) -> FactorContext:
        return FactorContext(decision_at=DECISION, datasets=dataset or tables(),
                             data_snapshot_hash="snapshot-A")

    def test_future_price_financial_and_universe_perturbations_do_not_change_view(self) -> None:
        baseline = self.context()
        altered = tables()
        altered["prices"].loc[1, "close"] = 1e9
        altered["financial_summary"].loc[1, "profit"] = -1e9
        altered["universe"].loc[1, "code"] = "9999"
        changed = self.context(altered)
        for name in ("prices", "financial_summary"):
            pd.testing.assert_frame_equal(baseline.read(name), changed.read(name))
        pd.testing.assert_frame_equal(baseline.universe(), changed.universe())
        self.assertEqual(baseline.universe()["code"].tolist(), ["1001"])

    def test_unknown_or_naive_availability_rejected(self) -> None:
        for value in (None, "2025-01-07 09:00:00"):
            with self.subTest(value=value):
                data = tables()
                data["prices"].loc[0, "available_at"] = value
                with self.assertRaises(FactorContractError):
                    self.context(data)

    def test_returned_copy_does_not_mutate_nested_cells_or_source(self) -> None:
        data = tables()
        ctx = self.context(data)
        first = ctx.read("prices")
        first.loc[0, "metadata"]["tags"].append("changed")
        self.assertEqual(ctx.read("prices").loc[0, "metadata"]["tags"], ["original"])
        self.assertEqual(data["prices"].loc[0, "metadata"]["tags"], ["original"])

    def test_intraday_and_legacy_calendar_semantics(self) -> None:
        ctx = self.context()
        self.assertEqual(str(ctx.decision_at), "2025-01-07 01:00:00+00:00")
        self.assertEqual(ctx.read("prices")["date"].tolist(), ["2025-01-06"])
        with self.assertRaises(FactorContractError):
            ctx.read("prices", asof=FUTURE)
        data = tables()
        data["prices"].loc[0, "date"] = "2025-01-07 11:00:00"
        self.assertTrue(self.context(data).read("prices").empty)
        data["prices"].loc[0, "date"] = None
        with self.assertRaises(FactorContractError):
            self.context(data).read("prices")

    def test_result_duplicate_code_infinity_missing_and_nested_copy(self) -> None:
        with self.assertRaisesRegex(FactorContractError, "unique"):
            FactorResult(minimal(values=(1.0, 2.0), codes=("1001", "1001")),
                         pd.DataFrame(), {})
        with self.assertRaisesRegex(FactorContractError, "finite"):
            FactorResult(minimal(values=(float("inf"),)), pd.DataFrame(), {})
        result = FactorResult.from_legacy_dict({
            "minimal": minimal(values=(np.nan,)),
            "detail": pd.DataFrame({"code": ["1001"], "x": [{"items": [1]}]}),
            "summary": {"nested": {"items": [2]}}, "extra": {"items": [3]},
        }, factor_id="quality")
        self.assertTrue(result.minimal["factor_value"].isna().all())
        payload = result.to_legacy_dict()
        payload["detail"].loc[0, "x"]["items"].append(9)
        payload["summary"]["nested"]["items"].append(9)
        payload["extra"]["items"].append(9)
        self.assertEqual(result.detail.loc[0, "x"]["items"], [1])
        self.assertEqual(result.summary["nested"]["items"], [2])
        self.assertEqual(result.extras["extra"]["items"], [3])

    def test_cache_key_changes_for_all_required_identities(self) -> None:
        base = spec()
        def key(item: FactorSpec, snapshot: str = "A", universe: str = "U") -> str:
            return item.cache_key(data_snapshot_hash=snapshot,
                                  universe_identity=universe, decision_at=DECISION)
        base_key = key(base)
        self.assertNotEqual(base_key, key(spec(parameter=2)))
        self.assertNotEqual(base_key, key(spec(impl_version="2")))
        self.assertNotEqual(base_key, key(base, snapshot="B"))
        self.assertNotEqual(base_key, key(base, universe="V"))
        changed_schema = FactorSpec(base.id, base.version, base.implementation_id,
                                    base.implementation_version, "2.0", base.config)
        self.assertNotEqual(base_key, key(changed_schema))
        with self.assertRaises(TypeError):
            base.config["implementation"]["parameters"]["window"] = 99
        direct = {"nested": {"window": [1]}}
        direct_spec = FactorSpec("x", "1", "private.x", "1", "1.0", direct)
        direct["nested"]["window"].append(2)
        self.assertEqual(direct_spec.config["nested"]["window"], (1,))

    def test_legacy_roundtrip_loader_capability_and_no_public_momentum_substitution(self) -> None:
        registry = LegacyFactorRegistry()
        seen: dict[str, object] = {}
        def runner(*, universe: pd.DataFrame, rebalance_date: pd.Timestamp,
                   config: dict[str, object]) -> dict[str, object]:
            seen["universe"] = universe["code"].tolist()
            seen["prices"] = config["fundamental_loader"]()["close"].tolist()
            seen["fallback"] = config["allow_yfinance_fallback"]
            return {"minimal": minimal(), "detail": pd.DataFrame(),
                    "summary": {"ok": True}, "extra": "preserved"}
        registry.register_runner("quality", "1", runner)
        with self.assertRaisesRegex(FactorContractError, "missing loader"):
            LegacyFactorAdapter(registry).run(spec(), self.context())
        registry.register_loader("fundamental_loader", lambda ctx: lambda: ctx.read("prices"))
        result = LegacyFactorAdapter(registry).run(spec(), self.context())
        self.assertEqual(seen["universe"], ["1001"])
        self.assertEqual(seen["prices"], [10.0])
        self.assertFalse(seen["fallback"])
        self.assertEqual(result.to_legacy_dict()["extra"], "preserved")
        with self.assertRaisesRegex(FactorContractError, "cannot replace"):
            registry.bind(spec(factor_id="residual_momentum",
                               impl_id="public.momentum_12_1"), self.context())


if __name__ == "__main__":
    unittest.main()
