"""Append-only historical research-paper replay for frozen next-open schedules.

This module owns only new, caller-selected output workspaces. It does not use
the production Store, credentials, network APIs, or an existing paper ledger.
Historical replay is RESEARCH-ONLY because source-time availability is unknown.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any

from .local_cache import load_research_bars


class HistoricalPaperResearchError(ValueError):
    """A frozen input, replay event, or append-only journal is invalid."""


_HEX64 = re.compile(r"^[a-f0-9]{64}$")
_CASH_EPS = 1e-8
_QTY_EPS = 1e-10
_VALUATION = "original raw close; price-only mark, no dividend cash model"


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise HistoricalPaperResearchError("journal content is not finite canonical JSON") from None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _implementation_identity() -> dict[str, Any]:
    return {"schema": "kabuforge.historical_paper_runtime_identity.v1",
        "python_version": sys.version.split()[0],
        "historical_paper_research_sha256": _sha_file(Path(__file__).resolve()),
        "local_cache_sha256": _sha_file(Path(load_research_bars.__code__.co_filename).resolve())}


def _write_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _date(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HistoricalPaperResearchError(f"{label} must be canonical ISO YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise HistoricalPaperResearchError(f"{label} is not a valid calendar date") from None
    if parsed.isoformat() != value:
        raise HistoricalPaperResearchError(f"{label} is not a canonical calendar date")
    return value


def _finite(value: Any, label: str, *, positive: bool = False,
            nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise HistoricalPaperResearchError(f"{label} must be finite numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise HistoricalPaperResearchError(f"{label} must be finite numeric") from None
    if not math.isfinite(result):
        raise HistoricalPaperResearchError(f"{label} must be finite numeric")
    if positive and result <= 0:
        raise HistoricalPaperResearchError(f"{label} must be positive")
    if nonnegative and result < 0:
        raise HistoricalPaperResearchError(f"{label} must be nonnegative")
    return result


def _load_bars(manifest_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise HistoricalPaperResearchError("explicit frozen-bars manifest cannot be read") from None
    if not isinstance(manifest, dict) or manifest.get("kind") != "kabuforge_local_research_bars":
        raise HistoricalPaperResearchError("historical paper requires a frozen local-research-bars manifest")
    selection = manifest.get("selection")
    if not isinstance(selection, dict) or selection.get("price_basis") != "raw":
        raise HistoricalPaperResearchError("historical paper requires an explicitly frozen raw-price selection")
    try:
        loaded = load_research_bars(manifest_path,
            codes=selection.get("requested_codes", []),
            start_date=selection.get("start_date", ""), end_date=selection.get("end_date", ""),
            price_basis=selection.get("price_basis", ""),
            duplicate_policy=selection.get("duplicate_policy", "reject"),
            known_halt_policy=selection.get("known_halt_policy", "reject"))
    except Exception as exc:
        raise HistoricalPaperResearchError(
            f"frozen bars failed verification: {type(exc).__name__}: {exc}") from None
    if _sha_file(manifest_path) != _sha(manifest_bytes):
        raise HistoricalPaperResearchError("frozen-bars manifest changed while it was being loaded")
    rows = loaded.bars.to_dict(orient="records")
    identity = {"kind": loaded.source["kind"],
        "manifest_sha256": loaded.source["source_sha256"],
        "selected_data_sha256": loaded.selected_data_sha256,
        "selection_identity_sha256": loaded.identity_sha256,
        "pinned_identity_sha256": loaded.source["details"]["pinned_identity_sha256"],
        "pinned_selection": loaded.source["details"]["pinned_selection"],
        "price_basis": loaded.selection["price_basis"], "pit_guarantee": False,
        "source_availability": "history visibility unverified", "coverage": loaded.coverage,
        "selection": loaded.selection}
    codes: dict[str, set[str]] = {}
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("code", "")); day = _date(row.get("date"), "bar date")
        if not code or (day, code) in by_key:
            raise HistoricalPaperResearchError("frozen bars contain an empty code or duplicate code/date")
        try:
            opened = _finite(row.get("open"), f"open {code} {day}", positive=True)
            high = _finite(row.get("high"), f"high {code} {day}", positive=True)
            low = _finite(row.get("low"), f"low {code} {day}", positive=True)
            close = _finite(row.get("close"), f"close {code} {day}", positive=True)
            factor = _finite(row.get("adjustment_factor"), f"adjustment factor {code} {day}", positive=True)
        except HistoricalPaperResearchError:
            raise
        if factor != 1.0:
            raise HistoricalPaperResearchError(f"corporate-action/split event unsupported: {code} {day}")
        if high < max(opened, close) or low > min(opened, close) or low > high:
            raise HistoricalPaperResearchError(f"raw OHLC ordering is invalid: {code} {day}")
        if row.get("selected_price_basis") != "raw" or _finite(
                row.get("selected_price"), f"selected raw price {code} {day}", positive=True) != close:
            raise HistoricalPaperResearchError(f"selected signal price is not the original raw close: {code} {day}")
        row.update({"code": code, "date": day, "open": opened, "high": high,
                    "low": low, "close": close, "adjustment_factor": factor})
        by_key[(day, code)] = row
        codes.setdefault(code, set()).add(day)
    if len(codes) < 1 or not by_key:
        raise HistoricalPaperResearchError("frozen bars are empty")
    calendars = list(codes.values())
    if any(calendar != calendars[0] for calendar in calendars[1:]):
        raise HistoricalPaperResearchError("frozen bars do not have a complete common observed calendar")
    dates = sorted(calendars[0])
    return rows, identity, {"codes": sorted(codes), "dates": dates, "by_key": by_key}


def _check_report_identity(report: dict[str, Any], bars_identity: dict[str, Any]) -> None:
    if report.get("model") != "daily_bar_next_open_research_v1" or report.get("status", "COMPLETED") != "COMPLETED":
        raise HistoricalPaperResearchError("reference must be a completed daily_bar_next_open_research_v1 report")
    if report.get("readiness") != "RESEARCH-ONLY" or report.get("pit_guarantee") is not False:
        raise HistoricalPaperResearchError("reference must remain RESEARCH-ONLY with PIT unverified")
    if report.get("submitted") is not False:
        raise HistoricalPaperResearchError("reference report must declare submitted=false")
    semantics = report.get("price_basis_semantics")
    if not isinstance(semantics, dict) or semantics.get("valuation") != _VALUATION:
        raise HistoricalPaperResearchError("reference report must declare original raw-close price-only valuation")
    if semantics.get("pit_guarantee") is not False:
        raise HistoricalPaperResearchError("reference price semantics must explicitly leave PIT unverified")
    identity = report.get("input_identity")
    identity_kind = "input_identity"
    if not isinstance(identity, dict):
        identity = report.get("input_source")
        identity_kind = "input_source"
    if not isinstance(identity, dict):
        raise HistoricalPaperResearchError("reference report lacks a pinned frozen-bars identity")
    aliases = {"manifest_sha256": "manifest_sha256", "selected_data_sha256": "selected_data_sha256",
        "selection_identity_sha256": "selection_identity_sha256",
        "pinned_identity_sha256": "pinned_identity_sha256"}
    for report_key, bars_key in aliases.items():
        if identity.get(report_key) != bars_identity.get(bars_key):
            raise HistoricalPaperResearchError(f"reference input identity mismatch: {report_key}")
    selection = identity.get("selection", identity.get("pinned_selection"))
    expected_selection = bars_identity.get("selection")
    if selection != expected_selection:
        raise HistoricalPaperResearchError("reference selection does not match the frozen-bars manifest")
    if identity_kind == "input_source" and identity.get("kind") != "kabuforge_local_research_bars":
        raise HistoricalPaperResearchError("price research reference is not bound to frozen local bars")


def _period(day: str, frequency: str) -> Any:
    parsed = date.fromisoformat(day)
    if frequency == "daily":
        return day
    if frequency == "weekly":
        iso = parsed.isocalendar()
        return iso.year, iso.week
    return day[:7]


def _load_reference(report_path: Path, expected_sha256: str, bars_identity: dict[str, Any],
                    bars: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(expected_sha256, str) or not _HEX64.fullmatch(expected_sha256.lower()):
        raise HistoricalPaperResearchError("expected reference report SHA-256 must be 64 hex characters")
    try:
        raw = report_path.read_bytes()
        report = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise HistoricalPaperResearchError("explicit strategy report cannot be read") from None
    actual = _sha(raw)
    if actual != expected_sha256.lower():
        raise HistoricalPaperResearchError("reference report does not match its pinned SHA-256")
    if _sha_file(report_path) != actual:
        raise HistoricalPaperResearchError("reference report changed while being loaded")
    if not isinstance(report, dict):
        raise HistoricalPaperResearchError("reference report must be a JSON object")
    def reject_future_material(value: Any, location: str = "report") -> None:
        forbidden = {"evaluation_panel", "evaluation_panel.json", "forward_return", "label_rows",
                     "label_end_date", "label_available_at", "label_status"}
        if isinstance(value, dict):
            for key, nested in value.items():
                if str(key).strip().lower() in forbidden:
                    raise HistoricalPaperResearchError(f"reference contains forbidden future-label material: {location}.{key}")
                reject_future_material(nested, f"{location}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                reject_future_material(nested, f"{location}[{index}]")
    reject_future_material(report)
    _check_report_identity(report, bars_identity)
    recipe = report.get("strategy_recipe", report.get("recipe"))
    if not isinstance(recipe, dict):
        raise HistoricalPaperResearchError("reference report lacks an explicit strategy recipe")
    frequency = recipe.get("frequency")
    if frequency not in {"daily", "weekly", "monthly"}:
        raise HistoricalPaperResearchError("reference schedule frequency is unsupported")
    fee_pct = _finite(recipe.get("fee"), "strategy fee", nonnegative=True)
    if fee_pct > 5:
        raise HistoricalPaperResearchError("strategy fee exceeds supported [0, 5] percent")
    cash = _finite(recipe.get("cash"), "strategy initial cash", positive=True)
    if "initial_equity" in report and abs(_finite(report["initial_equity"], "reference initial equity", positive=True) - cash) > 1e-8:
        raise HistoricalPaperResearchError("reference initial equity and recipe cash differ")
    nav = report.get("nav")
    if not isinstance(nav, list) or len(nav) < 2:
        raise HistoricalPaperResearchError("reference must provide at least two daily NAV dates")
    nav_dates = [_date(row.get("at", row.get("date")), "reference NAV date")
                 for row in nav if isinstance(row, dict)]
    if len(nav_dates) != len(nav) or len(set(nav_dates)) != len(nav_dates):
        raise HistoricalPaperResearchError("reference NAV dates are malformed or duplicated")
    if nav_dates != sorted(nav_dates):
        raise HistoricalPaperResearchError("reference NAV dates must be chronological")
    date_index = {day: index for index, day in enumerate(bars["dates"])}
    if any(day not in date_index for day in nav_dates):
        raise HistoricalPaperResearchError("reference NAV window is outside the pinned observed calendar")
    indexes = [date_index[day] for day in nav_dates]
    if indexes != list(range(indexes[0], indexes[-1] + 1)):
        raise HistoricalPaperResearchError("reference NAV dates are not a contiguous observed-calendar window")
    schedule = report.get("order_schedule")
    if not isinstance(schedule, list):
        raise HistoricalPaperResearchError("reference must provide an explicit frozen order_schedule")
    if "order_schedule_hash" in report:
        schedule_hash = _sha(json.dumps(schedule, sort_keys=True, separators=(",", ":"),
                                   allow_nan=False).encode("utf-8"))
        if report["order_schedule_hash"] != schedule_hash:
            raise HistoricalPaperResearchError("reference frozen order-schedule hash does not match")
    schedule_by_date: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    seen_buy_by_date: set[str] = set()
    codes = set(bars["codes"]); all_dates = bars["dates"]
    signal_template = recipe.get("signal_template", report.get("strategy_template"))
    warmup_execution_index = None
    if signal_template == "price_momentum":
        lookback = recipe.get("lookback")
        if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 2:
            raise HistoricalPaperResearchError("price-momentum reference has invalid lookback")
        warmup_execution_index = lookback + 1
    elif signal_template == "sma_crossover":
        slow = recipe.get("slow_period")
        if isinstance(slow, bool) or not isinstance(slow, int) or slow < 3:
            raise HistoricalPaperResearchError("moving-average reference has invalid slow_period")
        warmup_execution_index = slow + 1
    warmup_execution_date = (all_dates[warmup_execution_index]
        if warmup_execution_index is not None and warmup_execution_index < len(all_dates) else None)
    for index, raw_order in enumerate(schedule):
        if not isinstance(raw_order, dict):
            raise HistoricalPaperResearchError(f"reference order {index} is not an object")
        signal = _date(raw_order.get("signal_date"), f"order {index} signal_date")
        execution = _date(raw_order.get("execution_date"), f"order {index} execution_date")
        code = str(raw_order.get("code", "")); side = raw_order.get("side")
        if code not in codes or side not in {"buy", "sell"}:
            raise HistoricalPaperResearchError(f"reference order {index} has unknown code or side")
        if side == "buy":
            seen_buy_by_date.add(execution)
        elif execution in seen_buy_by_date:
            raise HistoricalPaperResearchError(f"reference sell follows a buy on {execution}; declared schedule is not sell-first")
        if signal not in date_index or execution not in date_index:
            raise HistoricalPaperResearchError(f"reference order {index} is outside the frozen observed calendar")
        signal_index = date_index[signal]; execution_index = date_index[execution]
        if signal_index + 1 != execution_index:
            raise HistoricalPaperResearchError(f"reference order {index} violates strict D-1/next-observed-session timing")
        same_period = _period(signal, frequency) == _period(execution, frequency)
        if same_period and not (warmup_execution_date is not None
                                and execution == warmup_execution_date
                                and execution_index == warmup_execution_index):
            raise HistoricalPaperResearchError(f"reference order {index} is outside its declared rebalance boundary")
        if warmup_execution_index is not None and execution_index < warmup_execution_index:
            raise HistoricalPaperResearchError(f"reference order {index} precedes the declared signal warmup")
        if execution not in set(nav_dates):
            raise HistoricalPaperResearchError(f"reference order {index} execution date is outside its NAV window")
        quantity = _finite(raw_order.get("quantity"), f"order {index} quantity", positive=True)
        sizing_price = _finite(raw_order.get("sizing_price"), f"order {index} sizing price", positive=True)
        close = float(bars["by_key"][(signal, code)]["close"])
        if not math.isclose(sizing_price, close, rel_tol=1e-12, abs_tol=1e-10):
            raise HistoricalPaperResearchError(f"reference order {index} quantity is not tied to prior raw close")
        key = (execution, code)
        if key in seen:
            raise HistoricalPaperResearchError(f"duplicate frozen order for {code} on {execution}")
        seen.add(key)
        order = {"signal_date": signal, "execution_date": execution, "code": code,
                 "side": side, "quantity": quantity, "sizing_price": sizing_price}
        schedule_by_date.setdefault(execution, []).append(order)
    if _sha_file(report_path) != actual:
        raise HistoricalPaperResearchError("reference report changed during validation")
    return report, {"report_sha256": actual, "cash": cash, "fee_rate": fee_pct / 100.0,
        "frequency": frequency, "nav_dates": nav_dates, "schedule_by_date": schedule_by_date,
        "order_count": len(schedule), "strategy_hash": report.get("strategy_hash"),
        "input_hash": report.get("input_hash"), "model": report["model"]}


def _load_inputs(manifest: Path, report_path: Path, expected_sha256: str):
    rows, identity, bars = _load_bars(manifest)
    report, reference = _load_reference(report_path, expected_sha256, identity, bars)
    source = {"manifest_path": str(manifest), "manifest_sha256": identity["manifest_sha256"],
        "selected_data_sha256": identity["selected_data_sha256"],
        "selection_identity_sha256": identity["selection_identity_sha256"],
        "pinned_identity_sha256": identity["pinned_identity_sha256"],
        "report_path": str(report_path), "report_sha256": reference["report_sha256"],
        "strategy_hash": reference["strategy_hash"], "input_hash": reference["input_hash"]}
    source["implementation_identity"] = _implementation_identity()
    return rows, identity, bars, report, reference, source


def _event_payload(state: dict[str, Any], day: str, reference: dict[str, Any], bars: dict[str, Any],
                   source: dict[str, Any], seq: int, idempotency_key: str) -> dict[str, Any]:
    cash = float(state["cash"])
    positions = dict(state["positions"])
    fee_rate = float(reference["fee_rate"])
    fills: list[dict[str, Any]] = []; skips: list[dict[str, Any]] = []
    gross = 0.0; fees = 0.0
    for order in reference["schedule_by_date"].get(day, []):
        code = order["code"]; quantity = float(order["quantity"])
        opened = float(bars["by_key"][(day, code)]["open"])
        notional = quantity * opened
        if not math.isfinite(notional):
            raise HistoricalPaperResearchError(f"order notional overflow on {day} {code}")
        fee = notional * fee_rate
        if not math.isfinite(fee):
            raise HistoricalPaperResearchError(f"order fee overflow on {day} {code}")
        if order["side"] == "sell":
            held = positions[code]
            if quantity > held + _QTY_EPS:
                skips.append({**order, "open_price": opened, "quantity": quantity,
                    "held_quantity": held, "reason": "frozen sell exceeds actual long holding; shorting disabled"})
                continue
            if abs(quantity - held) <= _QTY_EPS:
                positions[code] = 0.0
            else:
                positions[code] = held - quantity
            cash += notional - fee
        elif notional + fee > cash + _CASH_EPS:
            skips.append({**order, "open_price": opened, "quantity": quantity,
                "cash_available": cash, "cash_required": notional + fee,
                "reason": "opening gap exceeds available cash; frozen quantity skipped without resize"})
            continue
        else:
            cash -= notional + fee
            positions[code] += quantity
        fills.append({**order, "date": day, "open_price": opened,
            "quantity": quantity, "notional": notional, "fee": fee,
            "cash_after_fill": cash})
        gross += notional; fees += fee
    if cash < -_CASH_EPS:
        raise HistoricalPaperResearchError(f"historical account cash invariant failed on {day}")
    cash = max(cash, 0.0)
    marked = []
    equity = cash
    for code in bars["codes"]:
        quantity = float(positions[code])
        if quantity < -_QTY_EPS:
            raise HistoricalPaperResearchError(f"long-only position invariant failed on {day} {code}")
        if quantity < 0:
            positions[code] = quantity = 0.0
        close = float(bars["by_key"][(day, code)]["close"])
        market_value = quantity * close
        if not math.isfinite(market_value):
            raise HistoricalPaperResearchError(f"marked position overflow on {day} {code}")
        equity += market_value
        if quantity > _QTY_EPS:
            marked.append({"code": code, "quantity": quantity,
                "raw_close": close, "market_value": market_value})
    if not math.isfinite(equity) or equity <= 0:
        raise HistoricalPaperResearchError(f"historical account equity is invalid on {day}")
    return {"schema": "kabuforge.historical_paper_event.v1", "cursor": seq,
        "idempotency_key": idempotency_key, "at": day,
        "clock_semantics": "historical replay clock; not evidence of source-time availability",
        "source_identity": {"manifest_sha256": source["manifest_sha256"],
            "selected_data_sha256": source["selected_data_sha256"],
            "reference_report_sha256": source["report_sha256"],
            "implementation_identity": source["implementation_identity"]},
        "orders_considered": len(reference["schedule_by_date"].get(day, [])),
        "fills": fills, "skips": skips, "fees": fees,
        "gross_executed_notional": gross, "cash": cash,
        "positions": marked, "equity": equity,
        "nav": equity / float(reference["cash"]),
        "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
        "submitted": False}


def _read_events(journal_path: Path, contract_hash: str) -> list[dict[str, Any]]:
    try:
        raw = journal_path.read_bytes()
    except OSError:
        raise HistoricalPaperResearchError("append-only paper journal is missing") from None
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise HistoricalPaperResearchError("journal ends with a partial, uncommitted line")
    events = []
    previous_hash = contract_hash
    used_keys = set()
    for seq, line in enumerate(raw.splitlines()):
        try:
            event = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            raise HistoricalPaperResearchError(f"journal line {seq + 1} is not valid JSON") from None
        if not isinstance(event, dict) or event.get("cursor") != seq:
            raise HistoricalPaperResearchError(f"journal cursor is invalid at event {seq}")
        if event.get("previous_event_sha256") != previous_hash:
            raise HistoricalPaperResearchError(f"journal hash chain is broken at event {seq}")
        event_hash = event.pop("event_sha256", None)
        if not isinstance(event_hash, str) or not _HEX64.fullmatch(event_hash):
            raise HistoricalPaperResearchError(f"journal event hash is invalid at event {seq}")
        if _sha(_canonical(event)) != event_hash:
            raise HistoricalPaperResearchError(f"journal event content hash mismatch at event {seq}")
        key = event.get("idempotency_key")
        if not isinstance(key, str) or not key or key in used_keys:
            raise HistoricalPaperResearchError(f"journal idempotency key is invalid or repeated at event {seq}")
        used_keys.add(key)
        event["event_sha256"] = event_hash
        events.append(event)
        previous_hash = event_hash
    return events


@contextmanager
def _writer_lock(root: Path):
    lock_path = root / ".writer.lock"
    try:
        with lock_path.open("x", encoding="ascii") as stream:
            stream.write("historical_paper_research\n")
    except FileExistsError:
        raise HistoricalPaperResearchError("another writer owns this isolated paper workspace") from None
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


class HistoricalPaperResearch:
    """One private append-only research ledger with explicit chronological steps."""

    def __init__(self, output_dir: Path):
        self.root = output_dir.resolve(strict=True)
        self.contract_path = self.root / "contract.json"
        self.journal_path = self.root / "journal.jsonl"
        if (self.root / "failure.json").exists():
            raise HistoricalPaperResearchError("historical paper workspace has a failure receipt and is not resumable")
        try:
            self.contract_raw = self.contract_path.read_bytes()
            self.contract = json.loads(self.contract_raw)
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise HistoricalPaperResearchError("historical paper contract cannot be read") from None
        self.contract_hash = _sha(self.contract_raw)
        if (not isinstance(self.contract, dict)
                or self.contract.get("schema") != "kabuforge.historical_paper_contract.v1"
                or self.contract.get("status") != "PREREGISTERED"
                or self.contract.get("readiness") != "RESEARCH-ONLY"
                or self.contract.get("pit_guarantee") is not False):
            raise HistoricalPaperResearchError("workspace contract is unsupported or not RESEARCH-ONLY")
        if self.contract.get("implementation_identity") != _implementation_identity():
            raise HistoricalPaperResearchError("replay code/runtime identity changed since account creation")
        manifest = Path(self.contract["manifest_path"]).resolve(strict=True)
        report_path = Path(self.contract["strategy_report_path"]).resolve(strict=True)
        (self.rows, self.bars_identity, self.bars, self.report,
         self.reference, self.source_identity) = _load_inputs(
            manifest, report_path, self.contract["expected_report_sha256"])
        if self.source_identity != self.contract["source_identity"]:
            raise HistoricalPaperResearchError("frozen source identity changed since paper contract creation")
        events = _read_events(self.journal_path, self.contract_hash)
        self._verify_events(events)
        self._events = events
        self._verified_journal_sha256 = _sha_file(self.journal_path)

    @classmethod
    def create(cls, manifest_path: str | Path, strategy_report_path: str | Path,
               expected_report_sha256: str, output_dir: str | Path) -> "HistoricalPaperResearch":
        root = Path(output_dir).resolve()
        if root.exists():
            raise FileExistsError(root)
        manifest = Path(manifest_path).resolve(strict=True)
        report_path = Path(strategy_report_path).resolve(strict=True)
        # The report and source are read only to preregister their exact identities;
        # no existing account/ledger path is accepted or opened.
        manifest_sha = _sha_file(manifest)
        report_sha = _sha_file(report_path)
        if report_sha != str(expected_report_sha256).lower():
            raise HistoricalPaperResearchError("reference report does not match its pinned SHA-256")
        root.mkdir(parents=True, exist_ok=False)
        created = datetime.now(timezone.utc).isoformat()
        try:
            rows, bars_identity, bars, report, reference, source = _load_inputs(
                manifest, report_path, expected_report_sha256)
            if source["manifest_sha256"] != manifest_sha:
                raise HistoricalPaperResearchError("frozen manifest changed before contract preregistration")
            contract = {"schema": "kabuforge.historical_paper_contract.v1",
                "status": "PREREGISTERED", "created_at": created,
                "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
                "clock_semantics": "historical replay clock; not source-time availability",
                "account": {"currency": "JPY", "initial_cash": reference["cash"],
                    "fractional_shares": True, "broker_submission": False},
                "manifest_path": str(manifest), "strategy_report_path": str(report_path),
                "expected_report_sha256": reference["report_sha256"],
                "source_identity": source,
                "implementation_identity": _implementation_identity(),
                "strategy": {"model": reference["model"], "strategy_hash": reference["strategy_hash"],
                    "input_hash": reference["input_hash"], "fee_rate": reference["fee_rate"],
                    "frequency": reference["frequency"], "order_count": reference["order_count"],
                    "nav_start": reference["nav_dates"][0], "nav_end": reference["nav_dates"][-1]},
                "prohibited": ["no-network", "no-credentials", "no-production-store",
                    "no-existing-ledger", "no-broker-submission", "no-forward-labels",
                    "no-inferred-available-at", "not-PIT", "not-PAPER-READY"]}
            contract_path = root / "contract.json"
            _write_new(contract_path, contract)
            (root / "journal.jsonl").open("x", encoding="utf-8").close()
            return cls(root)
        except Exception as exc:
            failure = {"schema": "kabuforge.historical_paper_failure.v1", "status": "FAILED",
                "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
                "error_type": type(exc).__name__, "reason": str(exc),
                "manifest_sha256": manifest_sha, "expected_report_sha256": str(expected_report_sha256).lower()}
            try:
                _write_new(root / "failure.json", failure)
            except OSError:
                pass
            if isinstance(exc, HistoricalPaperResearchError):
                raise
            raise HistoricalPaperResearchError(f"historical paper creation failed: {type(exc).__name__}: {exc}") from None

    @classmethod
    def open(cls, output_dir: str | Path) -> "HistoricalPaperResearch":
        """Reopen and verify an existing workspace without advancing its cursor."""
        return cls(Path(output_dir))

    def _state_before(self, cursor: int) -> dict[str, Any]:
        if cursor == 0:
            return {"cash": float(self.reference["cash"]),
                    "positions": {code: 0.0 for code in self.bars["codes"]}}
        prior = self._events[cursor - 1]
        positions = {code: 0.0 for code in self.bars["codes"]}
        for item in prior["positions"]:
            positions[item["code"]] = float(item["quantity"])
        return {"cash": float(prior["cash"]), "positions": positions}

    def _verify_events(self, events: list[dict[str, Any]]) -> None:
        nav_dates = self.reference["nav_dates"]
        if len(events) > len(nav_dates):
            raise HistoricalPaperResearchError("journal contains more replay events than observed strategy dates")
        source = self.source_identity
        state = {"cash": float(self.reference["cash"]),
                 "positions": {code: 0.0 for code in self.bars["codes"]}}
        for seq, event in enumerate(events):
            if event.get("at") != nav_dates[seq]:
                raise HistoricalPaperResearchError(f"journal date is not chronological at cursor {seq}")
            expected = _event_payload(state, nav_dates[seq], self.reference, self.bars,
                source, seq, event["idempotency_key"])
            stored_payload = {key: value for key, value in event.items()
                              if key not in {"previous_event_sha256", "event_sha256"}}
            if _canonical(expected) != _canonical(stored_payload):
                raise HistoricalPaperResearchError(f"journal event does not match deterministic replay at cursor {seq}")
            state = {"cash": float(expected["cash"]),
                "positions": {code: 0.0 for code in self.bars["codes"]}}
            for item in expected["positions"]:
                state["positions"][item["code"]] = float(item["quantity"])

    def _refresh(self) -> None:
        if (self.root / "failure.json").exists():
            raise HistoricalPaperResearchError("historical paper workspace has a failure receipt and is not resumable")
        if _sha(self.contract_path.read_bytes()) != self.contract_hash:
            raise HistoricalPaperResearchError("paper contract changed after workspace creation")
        try:
            self._assert_sources_unchanged()
        except Exception as exc:
            self._record_failure("read_only_verification", exc)
            raise
        current_journal_hash = _sha_file(self.journal_path)
        if current_journal_hash != self._verified_journal_sha256:
            events = _read_events(self.journal_path, self.contract_hash)
            self._verify_events(events)
            self._events = events
            self._verified_journal_sha256 = current_journal_hash
        completion_path = self.root / "completion.json"
        if completion_path.exists():
            try:
                receipt = json.loads(completion_path.read_bytes())
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise HistoricalPaperResearchError("completion receipt is corrupt") from None
            if (len(self._events) != len(self.reference["nav_dates"])
                    or receipt.get("status") != "COMPLETED"
                    or receipt.get("contract_sha256") != self.contract_hash
                    or receipt.get("journal_sha256") != _sha_file(self.journal_path)
                    or receipt.get("implementation_identity") != _implementation_identity()):
                raise HistoricalPaperResearchError("completion receipt does not match the verified account journal")

    def _write_completion_receipt(self) -> None:
        if len(self._events) != len(self.reference["nav_dates"]):
            return
        path = self.root / "completion.json"
        if path.exists():
            self._refresh()
            return
        _write_new(path, {"schema": "kabuforge.historical_paper_completion.v1",
            "status": "COMPLETED", "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "contract_sha256": self.contract_hash,
            "journal_sha256": _sha_file(self.journal_path),
            "source_identity": self.source_identity,
            "implementation_identity": self.contract["implementation_identity"],
            "total_dates": len(self._events),
            "last_date": self._events[-1]["at"],
            "fills": sum(len(event["fills"]) for event in self._events),
            "skips": sum(len(event["skips"]) for event in self._events),
            "fees": sum(float(event["fees"]) for event in self._events),
            "completed_at_utc": datetime.now(timezone.utc).isoformat()})

    def cursor(self) -> int:
        """Return the next date index; querying never advances the replay."""
        self._refresh()
        return len(self._events)

    def complete(self) -> bool:
        self._refresh()
        return len(self._events) >= len(self.reference["nav_dates"])

    def events(self) -> list[dict[str, Any]]:
        """Return detached verified journal events without advancing."""
        self._refresh()
        return json.loads(json.dumps(self._events, ensure_ascii=False, allow_nan=False))

    def summary(self) -> dict[str, Any]:
        self._refresh()
        events = self._events
        last = events[-1] if events else None
        return {"status": "COMPLETED" if len(events) >= len(self.reference["nav_dates"]) else "IN_PROGRESS",
            "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
            "cursor": self.cursor(), "total_dates": len(self.reference["nav_dates"]),
            "last_date": last["at"] if last else None,
            "cash": last["cash"] if last else self.reference["cash"],
            "equity": last["equity"] if last else self.reference["cash"],
            "fills": sum(len(event["fills"]) for event in events),
            "skips": sum(len(event["skips"]) for event in events),
            "fees": sum(float(event["fees"]) for event in events),
            "journal_sha256": _sha_file(self.journal_path)}

    def _record_failure(self, stage: str, error: Exception) -> None:
        path = self.root / "failure.json"
        if path.exists():
            return
        try:
            _write_new(path, {"schema": "kabuforge.historical_paper_failure.v1",
                "status": "FAILED", "readiness": "RESEARCH-ONLY", "pit_guarantee": False,
                "stage": stage, "cursor": len(self._events),
                "error_type": type(error).__name__, "reason": str(error),
                "contract_sha256": self.contract_hash,
                "journal_sha256": _sha_file(self.journal_path),
                "source_identity": self.source_identity,
                "implementation_identity": self.contract["implementation_identity"],
                "recorded_at_utc": datetime.now(timezone.utc).isoformat()})
        except OSError:
            # The append-only journal remains authoritative if disk pressure
            # prevents a separate diagnostic receipt from being written.
            pass

    def _checked_source_identity(self, stage: str) -> None:
        try:
            self._assert_sources_unchanged()
        except Exception as exc:
            self._record_failure(stage, exc)
            raise

    def _build_event(self, state: dict[str, Any], day: str, seq: int,
                     idempotency_key: str, stage: str) -> dict[str, Any]:
        try:
            return _event_payload(state, day, self.reference, self.bars,
                                  self.source_identity, seq, idempotency_key)
        except Exception as exc:
            self._record_failure(stage, exc)
            raise

    def _assert_sources_unchanged(self) -> None:
        manifest = Path(self.contract["manifest_path"])
        report = Path(self.contract["strategy_report_path"])
        if _sha_file(manifest) != self.source_identity["manifest_sha256"]:
            raise HistoricalPaperResearchError("frozen-bars manifest changed during historical paper replay")
        if _sha_file(report) != self.source_identity["report_sha256"]:
            raise HistoricalPaperResearchError("strategy report changed during historical paper replay")
        # The local-cache frozen package is selected explicitly by the manifest.
        # Hash its canonical rows for each step, not the large original source data file.
        parsed = json.loads(manifest.read_text(encoding="utf-8"))
        artifacts = [parsed.get("canonical_data"), parsed.get("frozen_data")]
        if any(not isinstance(item, dict) or not isinstance(item.get("file"), str)
               or not isinstance(item.get("sha256"), str) for item in artifacts):
            raise HistoricalPaperResearchError("frozen-bars manifest lacks complete selected-data artifacts")
        frozen_root = manifest.parent.resolve(strict=True)
        for artifact in artifacts:
            selected_path = (frozen_root / artifact["file"]).resolve(strict=True)
            if frozen_root not in selected_path.parents:
                raise HistoricalPaperResearchError("frozen selected-data path escapes its workspace")
            if _sha_file(selected_path) != artifact["sha256"]:
                raise HistoricalPaperResearchError("frozen selected bars changed during replay")

    def step_next(self, *, idempotency_key: str | None = None,
                  expected_cursor: int | None = None) -> dict[str, Any] | None:
        """Append one daily event. Reuse the same idempotency key on retry."""
        self._refresh()
        if expected_cursor is not None and (isinstance(expected_cursor, bool)
                or not isinstance(expected_cursor, int) or expected_cursor < 0):
            raise HistoricalPaperResearchError("expected_cursor must be a nonnegative integer")
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 160:
                raise HistoricalPaperResearchError("idempotency_key must be 1..160 characters")
            for existing in self._events:
                if existing["idempotency_key"] == idempotency_key:
                    return json.loads(json.dumps(existing, ensure_ascii=False, allow_nan=False))
        cursor = len(self._events)
        if expected_cursor is not None and expected_cursor != cursor:
            raise HistoricalPaperResearchError(f"stale replay cursor: expected {expected_cursor}, current {cursor}")
        if cursor >= len(self.reference["nav_dates"]):
            return None
        key = idempotency_key or f"{self.contract_hash[:20]}:{cursor}"
        if any(event["idempotency_key"] == key for event in self._events):
            raise HistoricalPaperResearchError("idempotency key already belongs to another replay date")
        with _writer_lock(self.root):
            # Another process may have appended since this object was opened.
            current_hash = _sha_file(self.journal_path)
            if current_hash != self._verified_journal_sha256:
                fresh = _read_events(self.journal_path, self.contract_hash)
                self._verify_events(fresh)
                if len(fresh) != cursor:
                    raise HistoricalPaperResearchError("journal cursor changed in another writer")
                if fresh and fresh[-1]["event_sha256"] != (self._events[-1]["event_sha256"] if self._events else None):
                    raise HistoricalPaperResearchError("journal content changed in another writer")
            self._checked_source_identity("step_next.source_verification")
            day = self.reference["nav_dates"][cursor]
            state = self._state_before(cursor)
            payload = self._build_event(state, day, cursor, key, "step_next.replay")
            prev_hash = self.contract_hash if not self._events else self._events[-1]["event_sha256"]
            event = {**payload, "previous_event_sha256": prev_hash}
            event_hash = _sha(_canonical(event))
            event["event_sha256"] = event_hash
            line = _canonical(event) + b"\n"
            with self.journal_path.open("ab") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
            self._events.append(event)
            self._verified_journal_sha256 = _sha_file(self.journal_path)
            self._write_completion_receipt()
            return json.loads(json.dumps(event, ensure_ascii=False, allow_nan=False))

    def run_all(self) -> dict[str, Any]:
        """Append all remaining observed dates in order, then return the read-only summary."""
        self._refresh()
        with _writer_lock(self.root):
            fresh = _read_events(self.journal_path, self.contract_hash)
            self._verify_events(fresh)
            if len(fresh) != len(self._events) or (fresh and fresh[-1]["event_sha256"] != self._events[-1]["event_sha256"]):
                raise HistoricalPaperResearchError("journal changed before run-all acquired its writer lock")
            self._checked_source_identity("run_all.source_verification")
            state = self._state_before(len(self._events))
            while len(self._events) < len(self.reference["nav_dates"]):
                seq = len(self._events)
                if seq and seq % 64 == 0:
                    self._checked_source_identity("run_all.periodic_source_verification")
                day = self.reference["nav_dates"][seq]
                key = f"{self.contract_hash[:20]}:{seq}"
                payload = self._build_event(state, day, seq, key, "run_all.replay")
                previous_hash = self.contract_hash if not self._events else self._events[-1]["event_sha256"]
                event = {**payload, "previous_event_sha256": previous_hash}
                event["event_sha256"] = _sha(_canonical(event))
                with self.journal_path.open("ab") as stream:
                    stream.write(_canonical(event) + b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                self._events.append(event)
                state = {"cash": float(event["cash"]),
                    "positions": {code: 0.0 for code in self.bars["codes"]}}
                for item in event["positions"]:
                    state["positions"][item["code"]] = float(item["quantity"])
            self._checked_source_identity("run_all.final_source_verification")
            self._write_completion_receipt()
            self._verified_journal_sha256 = _sha_file(self.journal_path)
        return self.summary()


def create_historical_paper_research(manifest_path: str | Path,
        strategy_report_path: str | Path, expected_report_sha256: str,
        output_dir: str | Path) -> HistoricalPaperResearch:
    """Create a new isolated research-paper account from a frozen replay schedule."""
    return HistoricalPaperResearch.create(manifest_path, strategy_report_path,
                                          expected_report_sha256, output_dir)


def open_historical_paper_research(output_dir: str | Path) -> HistoricalPaperResearch:
    """Open and verify an existing isolated account without advancing it."""
    return HistoricalPaperResearch.open(output_dir)


__all__ = ["HistoricalPaperResearch", "HistoricalPaperResearchError",
    "create_historical_paper_research", "open_historical_paper_research"]
