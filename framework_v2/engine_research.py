"""Research-only replay of a frozen Native daily-bar order schedule.

The Native schedule is generated from an explicit frozen local-bars manifest
and one fixed recipe. Optional engines replay those exact quantities; they do
not generate signals, resize orders, call a network, or touch trading ledgers.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import importlib
from importlib import metadata
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable

from .price_research import _load_price_research_input, research_bars


class EngineResearchError(ValueError):
    """A frozen replay input or engine result violated its contract."""


DEFAULT_RECIPE = {
    "signal_template": "price_momentum",
    "lookback": 20,
    "count": 2,
    "frequency": "monthly",
    "cash": 2_000_000.0,
    "fee": 0.1,  # price_research contract: percent, so 0.1 means 0.1%.
}
_BACKENDS = {"vectorbt": "vectorbt", "backtrader": "backtrader"}
_TOLERANCE = {"absolute": 1e-6, "relative": 1e-9}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _finite_tree(value: Any, path: str = "result") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _finite_tree(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _finite_tree(item, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise EngineResearchError(f"non-finite financial output at {path}")


def _normalise_diagnostic_logs(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Replace library-log NaN/Inf only, and report every affected field count."""
    counts: dict[str, int] = {}
    clean = []
    for record in records:
        item = {}
        for field, value in record.items():
            if isinstance(value, float) and not math.isfinite(value):
                counts[field] = counts.get(field, 0) + 1
                item[field] = None
            else:
                item[field] = value
        clean.append(item)
    return clean, counts


def _write_new(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _source_hashes() -> dict[str, str]:
    from . import local_cache, price_research

    return {"engine_research.py": _sha_file(Path(__file__).resolve()),
            "price_research.py": _sha_file(Path(price_research.__file__).resolve()),
            "local_cache.py": _sha_file(Path(local_cache.__file__).resolve())}


def _runtime_record(backend: str) -> dict[str, Any]:
    module_name = _BACKENDS[backend]
    try:
        version = metadata.version(module_name)
    except metadata.PackageNotFoundError:
        version = None
    return {"backend": backend, "distribution": module_name,
            "version": version, "python": sys.version.split()[0],
            "implementation": sys.implementation.name}


def _require_frozen_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise EngineResearchError("frozen bars manifest cannot be read") from None
    if not isinstance(manifest, dict) or manifest.get("kind") != "kabuforge_local_research_bars":
        raise EngineResearchError("engine replay requires one kabuforge_local_research_bars manifest")
    selection = manifest.get("selection")
    if not isinstance(selection, dict) or not selection.get("requested_codes"):
        raise EngineResearchError("frozen bars manifest has no pinned security selection")
    return manifest


def _load_frozen_rows(manifest_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    before = _sha_file(manifest_path)
    manifest = _require_frozen_manifest(manifest_path)
    try:
        rows, identity = _load_price_research_input(manifest_path)
    except Exception as exc:
        raise EngineResearchError(f"frozen bars could not be verified: {type(exc).__name__}: {exc}") from None
    if _sha_file(manifest_path) != before:
        raise EngineResearchError("frozen bars manifest changed while it was being loaded")
    if not rows or not isinstance(identity, dict) or identity.get("kind") != "kabuforge_local_research_bars":
        raise EngineResearchError("frozen bars reader returned an unsupported input identity")
    if identity.get("pit_guarantee") is not False:
        raise EngineResearchError("frozen bars must retain explicit unverified-PIT status")
    identity = {**identity, "manifest_sha256": before,
                "manifest_path": str(manifest_path),
                "selection": manifest["selection"]}
    return rows, identity, before


def _validate_schedule(report: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    by_code: dict[str, set[str]] = {}
    for row in rows:
        by_code.setdefault(str(row["code"]), set()).add(str(row["date"]))
    dates = sorted(set.union(*by_code.values()))
    date_index = {day: i for i, day in enumerate(dates)}
    seen: set[tuple[str, str]] = set()
    previous_key: tuple[int, int] | None = None
    for order in report.get("order_schedule", []):
        try:
            signal_date = date.fromisoformat(str(order["signal_date"])).isoformat()
            execution_date = date.fromisoformat(str(order["execution_date"])).isoformat()
            code = str(order["code"])
            side = str(order["side"])
            quantity = float(order["quantity"])
            sizing_price = float(order["sizing_price"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise EngineResearchError("Native order schedule contains malformed fields") from None
        if code not in by_code or signal_date not in date_index or execution_date not in date_index:
            raise EngineResearchError("Native order schedule references a bar outside the frozen calendar")
        if date_index[execution_date] != date_index[signal_date] + 1:
            raise EngineResearchError("Native order execution is not the next observed session")
        if side not in {"buy", "sell"} or not math.isfinite(quantity) or quantity <= 0:
            raise EngineResearchError("Native order side/quantity is invalid")
        if not math.isfinite(sizing_price) or sizing_price <= 0:
            raise EngineResearchError("Native order sizing price is invalid")
        if execution_date not in by_code[code]:
            raise EngineResearchError("Native order has no execution-date bar")
        key = (execution_date, code)
        if key in seen:
            raise EngineResearchError("Native schedule has multiple orders for one security/session")
        seen.add(key)
        sort_key = (date_index[execution_date], 0 if side == "sell" else 1)
        if previous_key is not None and sort_key < previous_key:
            raise EngineResearchError("Native schedule does not preserve date and sell-before-buy order")
        previous_key = sort_key
    return dates, sorted(by_code)


def _normalise_native(report: dict[str, Any], input_identity: dict[str, Any],
                      schedule_hash: str, recipe_hash: str) -> dict[str, Any]:
    nav_by_date = {item["at"]: item["nav"] for item in report.get("nav", [])}
    timeline = [{**item, "nav": nav_by_date[item["at"]]}
                for item in report["account_path"]]
    return {
        "schema": "kabuforge.engine_research_backend.v1", "backend": "native",
        "status": "COMPLETED", "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
        "frequency": "daily observed sessions", "annualization_sessions": 252,
        "price_basis": {"signal": report.get("signal_price_basis"),
                        "execution": "raw open", "valuation": "raw close"},
        "input_identity": input_identity, "recipe_sha256": recipe_hash,
        "order_schedule_sha256": schedule_hash,
        "runtime": {"backend": "native", "version": "price_research.research_bars"},
        "timeline": timeline, "fills": report["trades"],
        "skips": report["skipped_orders"], "fees": report["fees"],
        "assumptions": report["assumptions"],
    }


def _vectorbt_replay(rows: list[dict[str, Any]], dates: list[str], codes: list[str],
                     schedule: list[dict[str, Any]], initial_cash: float,
                     fee: float) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        vbt = importlib.import_module("vectorbt")
    except Exception as exc:
        raise EngineResearchError(f"optional VectorBT runtime unavailable: {type(exc).__name__}: {exc}") from None
    import numpy as np
    import pandas as pd

    row_map = {(str(row["date"]), str(row["code"])): row for row in rows}
    close = pd.DataFrame({code: [float(row_map[(day, code)]["close"]) for day in dates]
                          for code in codes}, index=pd.Index(dates, name="date"))
    opened = pd.DataFrame({code: [float(row_map[(day, code)]["open"]) for day in dates]
                           for code in codes}, index=close.index)
    size = pd.DataFrame(0.0, index=close.index, columns=codes)
    by_day: dict[str, list[dict[str, Any]]] = {}
    for order in schedule:
        by_day.setdefault(str(order["execution_date"]), []).append(order)
        sign = 1.0 if order["side"] == "buy" else -1.0
        size.loc[str(order["execution_date"]), str(order["code"])] = sign * float(order["quantity"])
    code_index = {code: i for i, code in enumerate(codes)}
    call_seq = []
    for day in dates:
        ordered = [code_index[str(order["code"])] for order in by_day.get(day, [])]
        ordered.extend(index for index, code in enumerate(codes)
                       if code not in {str(order["code"]) for order in by_day.get(day, [])})
        call_seq.append(ordered)
    portfolio = vbt.Portfolio.from_orders(
        close=close, size=size, size_type="amount", direction="longonly",
        price=opened, fees=fee, init_cash=initial_cash,
        cash_sharing=True, group_by=True, call_seq=np.asarray(call_seq, dtype=np.int64),
        allow_partial=False, raise_reject=False, log=True, update_value=True,
        freq="1D", attach_call_seq=True)

    def as_list(obj: Any) -> list[Any]:
        if hasattr(obj, "to_list"):
            values = obj.to_list()
        else:
            values = list(obj)
        if values and isinstance(values[0], (list, tuple)):
            values = [item[0] if len(item) == 1 else item for item in values]
        return values

    cash_values = as_list(portfolio.cash())
    equity_values = as_list(portfolio.value())
    assets = portfolio.assets()
    asset_values = assets.to_numpy(dtype=float).tolist()
    order_records = portfolio.orders.records_readable.to_dict(orient="records")
    raw_log_records = portfolio.logs.records_readable.to_dict(orient="records")
    log_records, log_nonfinite = _normalise_diagnostic_logs(raw_log_records)
    filled: dict[tuple[str, str], dict[str, Any]] = {}
    for item in order_records:
        ts = item.get("Timestamp")
        day = dates[int(ts)] if isinstance(ts, (int, np.integer)) else str(ts)[:10]
        code = str(item["Column"])
        side = str(item["Side"]).lower()
        filled[(day, code)] = {"date": day, "code": code, "side": side,
            "quantity": float(item["Size"]), "price": float(item["Price"]),
            "fee": float(item["Fees"]), "engine_order_id": int(item["Order Id"])}
    log_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in log_records:
        request_size = item.get("Request Size")
        if request_size is None or not math.isfinite(float(request_size)) or abs(float(request_size)) < 1e-12:
            continue
        ts = item.get("Timestamp")
        day = dates[int(ts)] if isinstance(ts, (int, np.integer)) else str(ts)[:10]
        log_by_key[(day, str(item["Column"]))] = item
    fills: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    for order in schedule:
        key = (str(order["execution_date"]), str(order["code"]))
        actual = filled.get(key)
        if actual is None:
            log = log_by_key.get(key, {})
            skips.append({**order, "reason": str(log.get("Result Status Info") or log.get("Result Status")
                                     or "no VectorBT fill record"),
                          "observed_status": log.get("Result Status"),
                          "actual_open_cash": log.get("Cash")})
        else:
            fills.append({**order, **actual,
                "quantity_matches_schedule": math.isclose(actual["quantity"], float(order["quantity"]),
                                                          rel_tol=1e-10, abs_tol=1e-10)})
    timeline = []
    daily_fees: dict[str, float] = {}
    for fill in fills:
        daily_fees[fill["date"]] = daily_fees.get(fill["date"], 0.0) + float(fill["fee"])
    cumulative_fees = 0.0
    for i, day in enumerate(dates):
        day_fee = daily_fees.get(day, 0.0)
        cumulative_fees += day_fee
        positions = [{"code": code, "quantity": float(asset_values[i][j]),
                      "mark_price": float(close.iloc[i, j]),
                      "market_value": float(asset_values[i][j]) * float(close.iloc[i, j])}
                     for j, code in enumerate(codes) if abs(float(asset_values[i][j])) > 1e-12]
        timeline.append({"at": day, "cash": float(cash_values[i]),
                         "equity": float(equity_values[i]),
                         "nav": float(equity_values[i]) / initial_cash,
                         "fees": day_fee, "cumulative_fees": cumulative_fees,
                         "positions": positions})
    if any(float(item["cash"]) < -1e-6 for item in timeline):
        raise EngineResearchError("VectorBT cash invariant failed")
    if any(float(position["quantity"]) < -1e-10
           for item in timeline for position in item["positions"]):
        raise EngineResearchError("VectorBT long-only position invariant failed")
    actual_fees = sum(item["fee"] for item in fills)
    result = {"schema": "kabuforge.engine_research_backend.v1", "backend": "vectorbt",
        "status": "COMPLETED", "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
        "frequency": "daily observed sessions", "annualization_sessions": 252,
        "timeline": timeline, "fills": fills, "skips": skips, "fees": actual_fees,
        "engine_logs": log_records,
        "engine_log_nonfinite_fields_replaced_with_null": log_nonfinite,
        "assumptions": ["VectorBT Portfolio.from_orders; shared cash; fixed signed quantities",
            "fills at raw next-session open; equity marks at raw close",
            "allow_partial=False; fees are proportional; no slippage",
            "library diagnostic log NaN/Inf fields are null only in engine_logs; affected field counts are recorded"]}
    _finite_tree({key: value for key, value in result.items() if key != "engine_logs"}, "vectorbt")
    return (result,
        {"backend": "vectorbt", "version": getattr(vbt, "__version__", None),
         "numpy": np.__version__, "pandas": pd.__version__})


def _backtrader_replay(rows: list[dict[str, Any]], dates: list[str], codes: list[str],
                       schedule: list[dict[str, Any]], initial_cash: float,
                       fee: float) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        bt = importlib.import_module("backtrader")
    except Exception as exc:
        raise EngineResearchError(f"optional Backtrader runtime unavailable: {type(exc).__name__}: {exc}") from None
    import pandas as pd

    by_code: dict[str, list[dict[str, Any]]] = {code: [] for code in codes}
    for row in rows:
        by_code[str(row["code"])].append(row)
    schedule_by_signal: dict[str, list[dict[str, Any]]] = {}
    for order in schedule:
        schedule_by_signal.setdefault(str(order["signal_date"]), []).append(order)
    for day_orders in schedule_by_signal.values():
        day_orders.sort(key=lambda order: (0 if order["side"] == "sell" else 1,
                                           schedule.index(order)))

    class FrozenScheduleStrategy(bt.Strategy):
        params = (("frozen_schedule", schedule_by_signal), ("security_codes", tuple(codes)))

        def __init__(self):
            self._data_by_code = {code: self.getdatabyname(code) for code in self.p.security_codes}
            self._order_meta: dict[int, dict[str, Any]] = {}
            self.fills: list[dict[str, Any]] = []
            self.skips: list[dict[str, Any]] = []
            self.timeline: list[dict[str, Any]] = []

        def next(self):
            day = self.datas[0].datetime.date(0).isoformat()
            for frozen in self.p.frozen_schedule.get(day, []):
                data = self._data_by_code[frozen["code"]]
                qty = float(frozen["quantity"])
                if frozen["side"] == "sell":
                    actual_position = float(self.getposition(data).size)
                    if actual_position < 0:
                        raise EngineResearchError("Backtrader long-only invariant found a short position")
                    if qty > actual_position:
                        self.skips.append({**frozen,
                            "reason": "frozen sell quantity exceeds this engine's actual long position; shorting is disabled",
                            "observed_status": "no_sufficient_long_position",
                            "actual_position_quantity": actual_position})
                        continue
                    order = self.sell(data=data, size=qty, exectype=bt.Order.Market)
                else:
                    order = self.buy(data=data, size=qty, exectype=bt.Order.Market)
                order.addinfo(frozen_schedule=dict(frozen))
                self._order_meta[order.ref] = dict(frozen)
            positions = []
            for code in self.p.security_codes:
                data = self._data_by_code[code]
                qty = float(self.getposition(data).size)
                mark = float(data.close[0])
                if abs(qty) > 1e-12:
                    positions.append({"code": code, "quantity": qty,
                                      "mark_price": mark, "market_value": qty * mark})
            equity = float(self.broker.getvalue())
            day_fees = sum(float(fill["fee"]) for fill in self.fills if fill["date"] == day)
            cumulative_fees = sum(float(fill["fee"]) for fill in self.fills)
            self.timeline.append({"at": day, "cash": float(self.broker.getcash()),
                "equity": equity, "nav": equity / initial_cash,
                "fees": day_fees, "cumulative_fees": cumulative_fees, "positions": positions})

        def notify_order(self, order):
            if order.status in (order.Submitted, order.Accepted):
                return
            frozen = self._order_meta.get(order.ref)
            if not frozen:
                return
            if order.status == order.Completed:
                executed_day = bt.num2date(order.executed.dt).date().isoformat()
                self.fills.append({**frozen, "date": executed_day,
                    "quantity": abs(float(order.executed.size)),
                    "side": "buy" if order.isbuy() else "sell",
                    "price": float(order.executed.price), "fee": float(order.executed.comm),
                    "engine_order_ref": int(order.ref)})
            elif order.status in (order.Margin, order.Rejected, order.Canceled, order.Expired):
                status = order.getstatusname()
                self.skips.append({**frozen, "reason": f"Backtrader {status} at next-bar open",
                    "observed_status": status,
                    "broker_cash_at_notification": float(self.broker.getcash())})

    cerebro = bt.Cerebro(stdstats=False)
    for code in codes:
        frame = pd.DataFrame(by_code[code])
        frame.index = pd.to_datetime(frame["date"], format="%Y-%m-%d")
        frame = frame.rename(columns={"openinterest": "openinterest"})
        if "openinterest" not in frame:
            frame["openinterest"] = 0.0
        cerebro.adddata(bt.feeds.PandasData(dataname=frame[["open", "high", "low", "close", "volume", "openinterest"]]), name=code)
    cerebro.addstrategy(FrozenScheduleStrategy)
    broker = cerebro.broker
    broker.setcash(initial_cash)
    broker.setcommission(commission=fee, commtype=bt.CommInfoBase.COMM_PERC,
                         percabs=True, stocklike=True)
    broker.set_checksubmit(False)
    broker.set_coc(False)
    if hasattr(broker, "set_shortcash"):
        broker.set_shortcash(False)
    strategies = cerebro.run(runonce=False)
    strategy = strategies[0]
    if any(float(item["cash"]) < -1e-6 for item in strategy.timeline):
        raise EngineResearchError("Backtrader cash invariant failed")
    if any(float(position["quantity"]) < -1e-10
           for item in strategy.timeline for position in item["positions"]):
        raise EngineResearchError("Backtrader long-only position invariant failed")
    fills = strategy.fills
    actual = {(item["date"], item["code"]): item for item in fills}
    skips = list(strategy.skips)
    skipped_keys = {(item["execution_date"], item["code"]) for item in skips}
    for order in schedule:
        key = (str(order["execution_date"]), str(order["code"]))
        if key not in actual and key not in skipped_keys:
            skips.append({**order, "reason": "Backtrader produced no completion or rejection notification",
                          "observed_status": "missing_notification"})
    result = {"schema": "kabuforge.engine_research_backend.v1", "backend": "backtrader",
        "status": "COMPLETED", "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
        "frequency": "daily observed sessions", "annualization_sessions": 252,
        "timeline": strategy.timeline, "fills": fills, "skips": skips,
        "fees": sum(float(item["fee"]) for item in fills),
        "assumptions": ["Backtrader Market orders submitted after the signal-date close and processed on the next bar",
            "cheat-on-close disabled; broker pre-submit cash check disabled so cash is checked at execution open",
            "raw OHLCV bars; proportional commission; no filler or slippage",
            "frozen sell quantities exceeding actual long holdings are rejected; quantities are never resized"]}
    _finite_tree(result, "backtrader")
    return (result,
        {"backend": "backtrader", "version": getattr(bt, "__version__", None),
         "pandas": pd.__version__, "set_checksubmit": False, "cheat_on_close": False})


def _compare(native: dict[str, Any], other: dict[str, Any], tolerance: dict[str, float]) -> dict[str, Any]:
    native_timeline = {item["at"]: item for item in native["timeline"]}
    other_timeline = {item["at"]: item for item in other["timeline"]}
    rows = []
    daily_exceedances = []
    for day in sorted(set(native_timeline) | set(other_timeline)):
        left = native_timeline.get(day)
        right = other_timeline.get(day)
        if left is None or right is None:
            diff = {"date": day, "missing_from": "native" if left is None else other["backend"]}
            daily_exceedances.append(diff); rows.append(diff); continue
        metrics = {}
        for name in ("cash", "equity", "nav", "fees", "cumulative_fees"):
            a = float(left.get(name, 0.0)); b = float(right.get(name, 0.0)); absolute = abs(a - b)
            allowed = float(tolerance["absolute"]) + float(tolerance["relative"]) * max(abs(a), abs(b))
            metrics[name] = {"native": a, other["backend"]: b, "absolute_difference": absolute,
                             "within_tolerance": absolute <= allowed, "tolerance": allowed}
            if absolute > allowed:
                daily_exceedances.append({"date": day, "metric": name, **metrics[name]})
        positions_a = {item["code"]: float(item["quantity"]) for item in left.get("positions", [])}
        positions_b = {item["code"]: float(item["quantity"]) for item in right.get("positions", [])}
        position_diffs = {}
        for code in sorted(set(positions_a) | set(positions_b)):
            a = positions_a.get(code, 0.0); b = positions_b.get(code, 0.0)
            delta = abs(a - b)
            allowed = float(tolerance["absolute"]) + float(tolerance["relative"]) * max(abs(a), abs(b))
            position_diffs[code] = {"native": a, other["backend"]: b,
                                    "absolute_difference": delta, "within_tolerance": delta <= allowed}
            if delta > allowed:
                daily_exceedances.append({"date": day, "metric": "position_quantity", "code": code,
                                    **position_diffs[code]})
        rows.append({"date": day, **metrics, "positions": position_diffs})
    def order_summary(result):
        return [{"execution_date": item.get("execution_date", item.get("date")),
                 "code": item.get("code"), "side": item.get("side"),
                 "quantity": float(item.get("quantity", 0.0)),
                 "price": float(item.get("price", 0.0)),
                 "fee": float(item.get("fee", 0.0))}
                for item in result.get("fills", [])]
    def skip_summary(result):
        return [{"execution_date": item.get("execution_date", item.get("date")),
                 "code": item.get("code"), "side": item.get("side"),
                 "quantity": float(item.get("quantity", 0.0)),
                 "semantic_reason": _skip_semantics(item.get("reason", "")),
                 "engine_reason": item.get("reason"),
                 "observed_status": item.get("observed_status")}
                for item in result.get("skips", [])]
    left_fills = {(item["execution_date"], item["code"]): item for item in order_summary(native)}
    right_fills = {(item["execution_date"], item["code"]): item for item in order_summary(other)}
    fill_differences = []
    for key in sorted(set(left_fills) | set(right_fills)):
        a = left_fills.get(key); b = right_fills.get(key)
        fields = {}
        if a is None or b is None:
            fill_differences.append({"execution_date": key[0], "code": key[1],
                                     "native": a, other["backend"]: b})
            continue
        if a["side"] != b["side"]:
            fields["side"] = {"native": a["side"], other["backend"]: b["side"]}
        for name in ("quantity", "price", "fee"):
            delta = abs(float(a[name]) - float(b[name]))
            allowed = float(tolerance["absolute"]) + float(tolerance["relative"]) * max(
                abs(float(a[name])), abs(float(b[name])))
            if delta > allowed:
                fields[name] = {"native": a[name], other["backend"]: b[name],
                                "absolute_difference": delta, "tolerance": allowed}
        if fields:
            fill_differences.append({"execution_date": key[0], "code": key[1], "differences": fields})
    left_skips = {(item["execution_date"], item["code"]): item for item in skip_summary(native)}
    right_skips = {(item["execution_date"], item["code"]): item for item in skip_summary(other)}
    skip_differences = []
    for key in sorted(set(left_skips) | set(right_skips)):
        a = left_skips.get(key); b = right_skips.get(key)
        if a is None or b is None or a["side"] != b["side"] or a["semantic_reason"] != b["semantic_reason"]:
            skip_differences.append({"execution_date": key[0], "code": key[1],
                                     "native": a, other["backend"]: b})
    fees_difference = float(other["fees"]) - float(native["fees"])
    fee_tolerance = float(tolerance["absolute"]) + float(tolerance["relative"]) * max(
        abs(float(native["fees"])), abs(float(other["fees"])))
    total_fee_diff = abs(fees_difference) > fee_tolerance
    daily_ok = not daily_exceedances
    stream_ok = not fill_differences and not skip_differences and not total_fee_diff
    status = ("MATCHED_WITHIN_TOLERANCE" if daily_ok and stream_ok else
              "EXECUTION_STREAM_DIFFERENCES" if daily_ok else "FINANCIAL_DIFFERENCES")
    return {"schema": "kabuforge.engine_research_comparison.v1", "reference": "native",
        "backend": other["backend"], "status": status,
        "daily_account_within_tolerance": daily_ok,
        "execution_stream_matches": stream_ok,
        "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
        "tolerance": tolerance, "daily_differences": rows,
        "daily_account_exceedances": daily_exceedances,
        "fees": {"native": native["fees"], other["backend"]: other["fees"],
                 "difference": fees_difference, "tolerance": fee_tolerance,
                 "within_tolerance": not total_fee_diff},
        "fill_count": {"native": len(native["fills"]), other["backend"]: len(other["fills"])},
        "skip_count": {"native": len(native["skips"]), other["backend"]: len(other["skips"])},
        "fills": {"native": order_summary(native), other["backend"]: order_summary(other)},
        "fill_differences": fill_differences,
        "skips": {"native": skip_summary(native), other["backend"]: skip_summary(other)},
        "skip_differences": skip_differences,
        "execution_semantics": {"native": "Native fixed-quantity research replay at next open",
            "vectorbt": "Portfolio.from_orders shared-cash call sequence at open; no partials",
            "backtrader": "Market order submitted after prior close, next-bar open; submit check disabled; actual broker cash check"},
        "note": "Native is a reference replay, not a truth oracle; account path and ordered fills/skips are compared separately."}


def _skip_semantics(reason: Any) -> str:
    text = str(reason).strip().lower()
    if any(token in text for token in ("opening gap", "partialfill", "margin", "cash_shortfall", "cash")):
        return "cash_unavailable_at_execution"
    if any(token in text for token in ("no_sufficient_long_position", "noopenposition", "position")):
        return "insufficient_long_position"
    if not text:
        return "unknown_engine_skip"
    return "engine_specific_skip"


def run_engine_research(manifest_path: str | Path, output_dir: str | Path,
                        recipe: dict[str, Any] | None = None, *,
                        backends: Iterable[str] = ("vectorbt", "backtrader"),
                        tolerance: dict[str, float] | None = None) -> Path:
    """Freeze a Native order schedule, replay it in requested engines, and compare.

    ``output_dir`` must be a new private directory. No source cache is changed.
    Native is always run. Optional engine import failures are recorded rather
    than replaced with an in-house imitation.
    """
    recipe_value = dict(DEFAULT_RECIPE if recipe is None else recipe)
    chosen_backends = list(dict.fromkeys(backends))
    if any(name not in _BACKENDS for name in chosen_backends):
        raise EngineResearchError("backend must be one of the static optional-engine allowlist")
    compare_tolerance = dict(_TOLERANCE if tolerance is None else tolerance)
    if set(compare_tolerance) != {"absolute", "relative"} or any(
        not math.isfinite(float(value)) or float(value) < 0 for value in compare_tolerance.values()
    ):
        raise EngineResearchError("comparison tolerance must contain finite nonnegative absolute and relative values")
    target = Path(output_dir).resolve()
    if target.exists():
        raise FileExistsError(target)
    target.mkdir(parents=True, exist_ok=False)
    manifest = Path(manifest_path).resolve(strict=True)
    source_hashes = _source_hashes()
    recipe_hash = _sha_bytes(_canonical(recipe_value))
    initial_cash = float(recipe_value.get("cash", float("nan")))
    fee = float(recipe_value.get("fee", float("nan"))) / 100.0
    contract = {"schema": "kabuforge.engine_research_contract.v1", "status": "PREREGISTERED",
        "created_at": datetime.now(timezone.utc).isoformat(), "readiness": "RESEARCH-ONLY",
        "pit_guarantee": False, "manifest_path": str(manifest),
        "manifest_sha256_before_run": _sha_file(manifest), "recipe": recipe_value,
        "recipe_sha256": recipe_hash, "requested_backends": chosen_backends,
        "reference_backend": "native", "fee_semantics": "price_research percent; 0.1 means 0.1%",
        "annualization": {"observed_frequency": "daily observed sessions", "sessions_per_year": 252},
        "comparison_tolerance": compare_tolerance, "source_sha256": source_hashes,
        "prohibited": ["no-network", "no-credentials", "no-ledger", "no-order-resizing",
                       "no-dynamic-user-module-imports", "not-PIT", "not-PAPER-READY"]}
    _write_new(target / "contract.json", contract)
    try:
        rows, input_identity, manifest_sha = _load_frozen_rows(manifest)
        if manifest_sha != contract["manifest_sha256_before_run"]:
            raise EngineResearchError("frozen bars manifest changed after contract preregistration")
        native_raw = research_bars(rows, recipe_value)
        dates, codes = _validate_schedule(native_raw, rows)
        schedule_hash = _sha_bytes(_canonical(native_raw["order_schedule"]))
        frozen_orders = {"schema": "kabuforge.engine_frozen_order_schedule.v1",
            "status": "FROZEN", "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "input_identity_sha256": input_identity.get("selection_identity_sha256"),
            "input_manifest_sha256": manifest_sha, "recipe_sha256": recipe_hash,
            "provider": "price_research.research_bars", "schedule_sha256": schedule_hash,
            "orders": native_raw["order_schedule"]}
        _write_new(target / "frozen_order_schedule.json", frozen_orders)
        native = _normalise_native(native_raw, input_identity, schedule_hash, recipe_hash)
        _write_new(target / "native.json", native)
        results: dict[str, dict[str, Any]] = {"native": native}
        statuses: dict[str, Any] = {}
        for backend in chosen_backends:
            try:
                if backend == "vectorbt":
                    result, runtime = _vectorbt_replay(rows, dates, codes,
                        native_raw["order_schedule"], initial_cash, fee)
                elif backend == "backtrader":
                    result, runtime = _backtrader_replay(rows, dates, codes,
                        native_raw["order_schedule"], initial_cash, fee)
                else:  # guarded by static allowlist above
                    raise EngineResearchError("backend is not allowed")
                result["input_identity"] = input_identity
                result["recipe_sha256"] = recipe_hash
                result["order_schedule_sha256"] = schedule_hash
                result["runtime"] = runtime
                result["source_sha256"] = source_hashes
                _write_new(target / f"{backend}.json", result)
                results[backend] = result
                statuses[backend] = {"status": "COMPLETED", "runtime": runtime}
            except Exception as exc:
                error = {"schema": "kabuforge.engine_research_backend_failure.v1",
                    "backend": backend, "status": "FAILED_OR_UNAVAILABLE",
                    "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
                    "error_type": type(exc).__name__, "reason": str(exc),
                    "order_schedule_sha256": schedule_hash}
                _write_new(target / f"{backend}_failure.json", error)
                statuses[backend] = {"status": error["status"], "error_type": error["error_type"],
                                     "reason": error["reason"]}
        comparisons = []
        for backend, result in results.items():
            if backend == "native":
                continue
            comparison = _compare(native, result, compare_tolerance)
            _write_new(target / f"comparison_{backend}.json", comparison)
            comparisons.append(comparison)
        receipt = {"schema": "kabuforge.engine_research_receipt.v1", "status": "COMPLETED",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "input_manifest_sha256": manifest_sha, "recipe_sha256": recipe_hash,
            "order_schedule_sha256": schedule_hash, "source_sha256": source_hashes,
            "backend_status": statuses, "comparison_status": {
                item["backend"]: item["status"] for item in comparisons},
            "artifacts": {path.name: _sha_file(path) for path in sorted(target.iterdir()) if path.is_file()}}
        _write_new(target / "receipt.json", receipt)
        return target / "receipt.json"
    except Exception as exc:
        failure = {"schema": "kabuforge.engine_research_failure.v1", "status": "FAILED",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "error_type": type(exc).__name__, "reason": str(exc),
            "contract_sha256": _sha_file(target / "contract.json"),
            "source_sha256": source_hashes}
        _write_new(target / "failure.json", failure)
        raise


__all__ = ["DEFAULT_RECIPE", "EngineResearchError", "run_engine_research"]
