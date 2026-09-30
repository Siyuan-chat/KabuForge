"""Local SQLite order journal and reservation gate; no broker/network operations.

SQLite COMMIT is the local atomic boundary, not a claim of broker exactly-once.
After SUBMITTING or UNKNOWN, callers must reconcile externally before any new
submission attempt.  ``register_batch`` reserves a whole plan under one write
transaction, across independent Store connections to the same explicit path.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from .execution import (AccountState, ExecutionError, Fill, OrderEvent, OrderIntent,
                        OrderPlan, OrderStatus, Position, aware, money)
from .models import TargetPortfolio


class StoreError(ValueError):
    """Journal conflict, revision conflict, or unsafe reservation."""


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False, default=str)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _target(value: TargetPortfolio | None) -> str:
    if value is None:
        return "null"
    if not isinstance(value, TargetPortfolio):
        raise StoreError("audit target must be TargetPortfolio or None")
    return _json([{"code": p.code, "weight": str(p.weight),
                   "amount": None if p.amount is None else str(p.amount)} for p in value.positions])


def _intent(item: OrderIntent) -> str:
    return _json({"intent_id": item.intent_id, "idempotency_key": item.idempotency_key,
                  "account_id": item.account_id, "account_revision": item.account_revision,
                  "decision_identity": item.decision_identity, "strategy_hash": item.strategy_hash,
                  "code": item.code, "side": item.side, "quantity": item.quantity,
                  "order_type": item.order_type, "limit_price": None if item.limit_price is None else str(item.limit_price),
                  "time_in_force": item.time_in_force, "created_at": item.created_at.isoformat(),
                  "valid_until": item.valid_until.isoformat(), "estimated_price": str(item.estimated_price),
                  "estimated_fee": str(item.estimated_fee)})


def _event(item: OrderEvent, trade_id: str | None) -> str:
    return _json({"event_id": item.event_id, "intent_id": item.intent_id,
                  "status": item.status.value, "occurred_at": item.occurred_at.isoformat(),
                  "broker_order_id": item.broker_order_id, "reason": item.reason,
                  "trade_id": trade_id})


def _fill(item: Fill) -> str:
    return _json({"intent_id": item.intent_id, "trade_id": item.trade_id,
                  "code": item.code, "side": item.side, "quantity": item.quantity,
                  "price": str(item.price), "fee": str(item.fee),
                  "occurred_at": item.occurred_at.isoformat()})


class Store:
    """Explicit-path journal.  No database is opened until constructed.

    ``begin_submission`` is one-shot and records SUBMITTING before caller I/O.
    A retry after an uncertain call must use broker reconciliation evidence via
    ``record_event``; neither registration nor begin_submission resends it.
    """

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)) or str(path) in {"", ":memory:"}:
            raise StoreError("an explicit persistent SQLite path is required")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            version=db.execute("PRAGMA user_version").fetchone()[0]
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version not in (0,1) or (version==0 and tables):
                raise StoreError("unversioned or unsupported journal schema; explicit migration required")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS run_evidence(
                    run_id TEXT PRIMARY KEY, payload TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(
                    run_id TEXT PRIMARY KEY, decision_identity TEXT NOT NULL,
                    strategy_hash TEXT NOT NULL, raw_target TEXT NOT NULL,
                    allowed_target TEXT NOT NULL, intent_ids TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts(
                    account_id TEXT PRIMARY KEY, revision TEXT NOT NULL,
                    base_revision TEXT NOT NULL, revision_count INTEGER NOT NULL,
                    equity TEXT NOT NULL, available_cash TEXT NOT NULL,
                    reconciliation_required INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS positions(
                    account_id TEXT NOT NULL, code TEXT NOT NULL, quantity INTEGER NOT NULL,
                    average_cost TEXT NOT NULL, PRIMARY KEY(account_id,code));
                CREATE TABLE IF NOT EXISTS orders(
                    intent_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL, account_id TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL, filled_quantity INTEGER NOT NULL,
                    reserved_cash TEXT NOT NULL, reserved_shares INTEGER NOT NULL,
                    status_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    event_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS fills(
                    trade_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reconciliations(
                    evidence_ref TEXT PRIMARY KEY, event_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS valuations(
                    valuation_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    resulting_revision TEXT NOT NULL);
            """)
            db.execute("PRAGMA user_version=1")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None,
                             factory=_ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _write(self, action: Callable[[sqlite3.Connection], Any],
               failure_hook: Callable[[str], None] | None = None) -> Any:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            result = action(db)
            if failure_hook:
                failure_hook("before_commit")
            db.commit()
            if failure_hook:
                failure_hook("after_commit")
            return result
        except Exception:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def register_batch(self, run_id: str, plan: OrderPlan, account: AccountState, *,
                       raw_target: TargetPortfolio | None = None,
                       allowed_target: TargetPortfolio | None = None,
                       decision_identity: str | None = None,
                       strategy_hash: str | None = None,
                       evidence: dict[str, Any] | None = None,
                       failure_hook: Callable[[str], None] | None = None) -> tuple[str, ...]:
        """Atomically save run/intents and reserve confirmed cash or held shares.

        Replaying an identical complete batch returns its IDs even if fills
        advanced revision.  Empty plans require explicit decision/strategy
        identity.  New batches cannot consume reserves or cross uncertain state.
        """
        if not isinstance(run_id, str) or not run_id or not isinstance(plan, OrderPlan) or not isinstance(account, AccountState):
            raise StoreError("run_id, plan, and account are required")
        raw_json, allowed_json = _target(raw_target), _target(allowed_target)
        if evidence is not None and not isinstance(evidence, dict):
            raise StoreError("run evidence must be an explicit JSON object")
        try:
            evidence_json=json.dumps(evidence or {},sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)
        except (TypeError,ValueError) as exc:
            raise StoreError("run evidence must be finite JSON") from exc
        if any(item.account_id != account.account_id or item.account_revision != account.revision
               for item in plan.intents):
            raise StoreError("plan account/revision mismatch")
        if any(item.decision_identity != plan.intents[0].decision_identity or
               item.strategy_hash != plan.intents[0].strategy_hash for item in plan.intents):
            raise StoreError("mixed decision/strategy in a batch")
        if plan.intents:
            decision = plan.intents[0].decision_identity
            strategy = plan.intents[0].strategy_hash
            if (decision_identity is not None and decision_identity != decision or
                    strategy_hash is not None and strategy_hash != strategy):
                raise StoreError("explicit run identity conflicts with intents")
        else:
            decision, strategy = decision_identity, strategy_hash
            if not isinstance(decision, str) or not decision or not isinstance(strategy, str) or not strategy:
                raise StoreError("empty plan requires decision_identity and strategy_hash")
        intent_ids = _json([item.intent_id for item in plan.intents])

        def action(db: sqlite3.Connection) -> tuple[str, ...]:
            old_evidence=db.execute("SELECT payload FROM run_evidence WHERE run_id=?",(run_id,)).fetchone()
            if old_evidence is not None and old_evidence["payload"]!=evidence_json:
                raise StoreError("run evidence changed")
            if old_evidence is None:
                db.execute("INSERT INTO run_evidence VALUES(?,?,?)",(run_id,evidence_json,_hash(evidence_json)))
            existing_run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if existing_run:
                if (existing_run["decision_identity"], existing_run["strategy_hash"],
                    existing_run["raw_target"], existing_run["allowed_target"], existing_run["intent_ids"]) != (
                    decision, strategy, raw_json, allowed_json, intent_ids):
                    raise StoreError("run_id already has a different audit payload")
            else:
                db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)",
                           (run_id, decision, strategy, raw_json, allowed_json, intent_ids))
            old_count = 0
            for item in plan.intents:
                payload = _intent(item)
                prior = db.execute("SELECT * FROM orders WHERE intent_id=? OR idempotency_key=?",
                                   (item.intent_id, item.idempotency_key)).fetchone()
                if prior:
                    if prior["intent_id"] != item.intent_id or prior["idempotency_key"] != item.idempotency_key or prior["payload_hash"] != _hash(payload) or prior["payload"] != payload or prior["run_id"] != run_id:
                        raise StoreError("idempotency key or intent ID has a different payload")
                    old_count += 1
            if old_count == len(plan.intents):
                if existing_run:
                    return tuple(item.intent_id for item in plan.intents)
                if plan.intents:
                    raise StoreError("existing intent IDs belong to another run")
            if existing_run:
                raise StoreError("run already registered with a different intent set")

            saved = db.execute("SELECT * FROM accounts WHERE account_id=?", (account.account_id,)).fetchone()
            if saved is None:
                db.execute("INSERT INTO accounts VALUES(?,?,?,?,?,?,?)",
                           (account.account_id, account.revision, account.revision, 0,
                            str(account.equity), str(account.available_cash), 0))
                for pos in account.positions:
                    db.execute("INSERT INTO positions VALUES(?,?,?,?)",
                               (account.account_id, pos.code, pos.quantity, str(pos.average_cost)))
            else:
                if saved["reconciliation_required"]:
                    raise StoreError("account requires reconciliation")
                if saved["revision"] != account.revision:
                    raise StoreError("stale account revision")
                stored_positions = [(r["code"], r["quantity"], r["average_cost"]) for r in
                                    db.execute("SELECT * FROM positions WHERE account_id=? ORDER BY code", (account.account_id,))]
                given_positions = [(p.code, p.quantity, str(p.average_cost)) for p in account.positions]
                if (Decimal(saved["available_cash"]) != account.available_cash or
                    Decimal(saved["equity"]) != account.equity or stored_positions != given_positions):
                    raise StoreError("same revision carries different account state")
            if db.execute("SELECT 1 FROM orders WHERE account_id=? AND status IN ('SUBMITTING','UNKNOWN') LIMIT 1",
                          (account.account_id,)).fetchone():
                raise StoreError("account has uncertain orders; reconcile first")
            reserved = db.execute("SELECT reserved_cash, reserved_shares, payload FROM orders WHERE account_id=?",
                                  (account.account_id,)).fetchall()
            cash_left = account.available_cash - sum((Decimal(r["reserved_cash"]) for r in reserved), Decimal(0))
            shares_left = {p.code: p.quantity for p in account.positions}
            for row in reserved:
                record = json.loads(row["payload"])
                shares_left[record["code"]] = shares_left.get(record["code"], 0) - row["reserved_shares"]
            for item in plan.intents:
                if db.execute("SELECT 1 FROM orders WHERE intent_id=?", (item.intent_id,)).fetchone():
                    continue
                if item.side == "buy":
                    cash_hold = item.estimated_price * item.quantity + item.estimated_fee
                    if cash_hold > cash_left:
                        raise StoreError("insufficient unreserved cash")
                    cash_left -= cash_hold
                    share_hold = 0
                else:
                    cash_hold = max(Decimal(0), item.estimated_fee - item.estimated_price * item.quantity)
                    if cash_hold > cash_left:
                        raise StoreError("insufficient unreserved cash for sale fee")
                    cash_left -= cash_hold
                    share_hold = item.quantity
                    if share_hold > shares_left.get(item.code, 0):
                        raise StoreError("insufficient unreserved shares")
                    shares_left[item.code] -= share_hold
                payload = _intent(item)
                db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (item.intent_id, item.idempotency_key, run_id, account.account_id,
                            payload, _hash(payload), "PLANNED", 0, str(cash_hold), share_hold,
                            item.created_at.isoformat()))
            return tuple(item.intent_id for item in plan.intents)

        return self._write(action, failure_hook)

    def begin_submission(self, intent_id: str, *,
                         failure_hook: Callable[[str], None] | None = None) -> None:
        """One-shot PLANNED -> SUBMITTING gate, committed before external I/O.

        The execution coordinator must check quote freshness and DAY validity
        immediately before calling; this journal does not implement a clock or
        exchange calendar.
        """
        def action(db: sqlite3.Connection) -> None:
            row = db.execute("SELECT status,account_id FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
            if row is None or row["status"] != "PLANNED":
                raise StoreError("submission requires a new PLANNED intent; reconcile uncertain orders")
            account = db.execute("SELECT reconciliation_required FROM accounts WHERE account_id=?",
                                 (row["account_id"],)).fetchone()
            if account is None or account["reconciliation_required"]:
                raise StoreError("account requires reconciliation")
            if db.execute("SELECT 1 FROM orders WHERE account_id=? AND status IN ('SUBMITTING','UNKNOWN') LIMIT 1",
                          (row["account_id"],)).fetchone():
                raise StoreError("account has uncertain orders; reconcile first")
            db.execute("UPDATE orders SET status='SUBMITTING' WHERE intent_id=?", (intent_id,))
        self._write(action, failure_hook)

    def record_event(self, event: OrderEvent, fill: Fill | None = None, *,
                     reconciliation_evidence: str | None = None,
                     failure_hook: Callable[[str], None] | None = None) -> None:
        """Commit an event and optional actual fill/account effect together.

        Events and trades deduplicate by stable IDs.  Old status evidence never
        rolls an order back.  A real late fill still books after cancellation.
        FILLED without quantity-level fill evidence remains UNKNOWN and gated.
        """
        if not isinstance(event, OrderEvent) or (fill is not None and not isinstance(fill, Fill)):
            raise StoreError("typed event/fill required")
        if fill is not None and fill.intent_id != event.intent_id:
            raise StoreError("event/fill intent mismatch")
        if reconciliation_evidence is not None and (not isinstance(reconciliation_evidence, str) or not reconciliation_evidence):
            raise StoreError("reconciliation_evidence must be nonempty text")
        event_payload = _event(event, None if fill is None else fill.trade_id)
        fill_payload = None if fill is None else _fill(fill)

        def action(db: sqlite3.Connection) -> None:
            order = db.execute("SELECT * FROM orders WHERE intent_id=?", (event.intent_id,)).fetchone()
            if order is None:
                raise StoreError("unknown intent")
            prior_event = db.execute("SELECT * FROM events WHERE event_id=?", (event.event_id,)).fetchone()
            if prior_event:
                if prior_event["payload"] != event_payload or prior_event["payload_hash"] != _hash(event_payload):
                    raise StoreError("event_id collision with different payload")
                if fill is not None:
                    prior_fill = db.execute("SELECT * FROM fills WHERE trade_id=?", (fill.trade_id,)).fetchone()
                    if prior_fill is None or prior_fill["payload"] != fill_payload or prior_fill["payload_hash"] != _hash(fill_payload):
                        raise StoreError("trade_id collision with different payload")
                self._record_evidence(db, event.event_id, reconciliation_evidence)
                return
            record = json.loads(order["payload"])
            new_filled = order["filled_quantity"]
            if fill is not None:
                if fill.code != record["code"] or fill.side != record["side"]:
                    raise StoreError("fill security/side mismatch")
                prior_fill = db.execute("SELECT * FROM fills WHERE trade_id=?", (fill.trade_id,)).fetchone()
                if prior_fill:
                    if prior_fill["payload"] != fill_payload or prior_fill["payload_hash"] != _hash(fill_payload):
                        raise StoreError("trade_id collision with different payload")
                else:
                    new_filled += fill.quantity
                    if new_filled > record["quantity"]:
                        raise StoreError("fills exceed intent quantity")
                    db.execute("INSERT INTO fills VALUES(?,?,?,?)",
                               (fill.trade_id, fill.intent_id, fill_payload, _hash(fill_payload)))
                    self._apply_fill(db, order["account_id"], fill)
            current = order["status"]
            requested = event.status.value
            if (current in {"SUBMITTING", "UNKNOWN"} and requested not in {"SUBMITTING", "UNKNOWN", "FILLED"}
                    and fill is None and reconciliation_evidence is None and event.broker_order_id is None):
                raise StoreError("explicit reconciliation evidence required")
            older = event.occurred_at < datetime.fromisoformat(order["status_at"])
            if new_filled == record["quantity"]:
                status = "FILLED"
            elif older:
                status = current
            elif requested == "FILLED":
                status = "UNKNOWN"  # reported complete, but trade detail is missing
            elif requested == "UNKNOWN":
                status = "UNKNOWN"  # later uncertainty always gates new orders
            elif current in {"CANCELED", "REJECTED", "FILLED"}:
                status = current
            elif requested in {"CANCELED", "REJECTED"}:
                status = requested
            elif current == "PARTIAL" and requested == "ACCEPTED":
                status = current
            else:
                status = requested
            if 0 < new_filled < record["quantity"] and status in {"PLANNED", "SUBMITTING", "ACCEPTED"}:
                status = "PARTIAL"
            remaining = record["quantity"] - new_filled
            terminal = status in {"CANCELED", "REJECTED", "FILLED"}
            reserved_shares = 0 if terminal or record["side"] == "buy" else remaining
            reserved_cash = Decimal(0)
            if not terminal and record["side"] == "buy":
                reserved_cash = Decimal(record["estimated_price"]) * remaining + Decimal(record["estimated_fee"])
            elif not terminal and record["side"] == "sell":
                reserved_cash = max(Decimal(0), Decimal(record["estimated_fee"]) -
                                    Decimal(record["estimated_price"]) * remaining)
            status_at = order["status_at"] if older else event.occurred_at.isoformat()
            db.execute("UPDATE orders SET status=?, filled_quantity=?, reserved_cash=?, reserved_shares=?, status_at=? WHERE intent_id=?",
                       (status, new_filled, str(reserved_cash), reserved_shares, status_at, event.intent_id))
            db.execute("INSERT INTO events VALUES(?,?,?,?)",
                       (event.event_id, event.intent_id, event_payload, _hash(event_payload)))
            self._record_evidence(db, event.event_id, reconciliation_evidence)

        self._write(action, failure_hook)

    def reconcile(self, event: OrderEvent, evidence_ref: str, fill: Fill | None = None) -> None:
        """Record caller-attested broker query evidence; never resubmit an order."""
        if not isinstance(evidence_ref, str) or not evidence_ref:
            raise StoreError("reconciliation requires a nonempty evidence reference")
        self.record_event(event, fill, reconciliation_evidence=evidence_ref)

    @staticmethod
    def _record_evidence(db: sqlite3.Connection, event_id: str, evidence_ref: str | None) -> None:
        if evidence_ref is None:
            return
        prior = db.execute("SELECT event_id FROM reconciliations WHERE evidence_ref=?", (evidence_ref,)).fetchone()
        if prior is not None and prior["event_id"] != event_id:
            raise StoreError("reconciliation evidence reference collision")
        if prior is None:
            db.execute("INSERT INTO reconciliations VALUES(?,?)", (evidence_ref, event_id))

    @staticmethod
    def _apply_fill(db: sqlite3.Connection, account_id: str, fill: Fill) -> None:
        account = db.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
        if account is None:
            raise StoreError("fill account missing")
        existing = db.execute("SELECT * FROM positions WHERE account_id=? AND code=?",
                              (account_id, fill.code)).fetchone()
        old_qty = 0 if existing is None else existing["quantity"]
        old_cost = Decimal(0) if existing is None else Decimal(existing["average_cost"])
        cash = Decimal(account["available_cash"])
        if fill.side == "buy":
            new_qty = old_qty + fill.quantity
            new_cost = (old_cost * old_qty + fill.price * fill.quantity) / new_qty
            cash -= fill.price * fill.quantity + fill.fee
        else:
            if fill.quantity > old_qty:
                raise StoreError("actual sale exceeds recorded position; reconcile account")
            new_qty = old_qty - fill.quantity
            new_cost = old_cost
            cash += fill.price * fill.quantity - fill.fee
        if new_qty:
            db.execute("INSERT INTO positions VALUES(?,?,?,?) ON CONFLICT(account_id,code) DO UPDATE SET quantity=excluded.quantity, average_cost=excluded.average_cost",
                       (account_id, fill.code, new_qty, str(new_cost)))
        else:
            db.execute("DELETE FROM positions WHERE account_id=? AND code=?", (account_id, fill.code))
        count = account["revision_count"] + 1
        revision = f"{account['base_revision']}#{count}"
        needs_reconcile = int(account["reconciliation_required"] or cash < 0)
        db.execute("UPDATE accounts SET revision=?, revision_count=?, available_cash=?, reconciliation_required=? WHERE account_id=?",
                   (revision, count, str(cash), needs_reconcile, account_id))

    def mark_account(self, account_id: str, expected_revision: str,
                     marks: Mapping[str, Decimal], valuation_id: str,
                     asof: datetime) -> str:
        """Atomically mark held shares and cash to equity, advancing revision.

        Every held code needs a finite positive mark.  Same valuation ID with
        identical payload returns the original resulting revision; a changed
        payload fails.  Cash, quantities, and uncertainty flags are preserved.
        Caller owns mark provenance and PIT validation; this method does no I/O
        beyond its explicitly opened local journal.
        """
        if (not isinstance(account_id, str) or not account_id or
                not isinstance(expected_revision, str) or not expected_revision or
                not isinstance(valuation_id, str) or not valuation_id):
            raise StoreError("account, revision, and valuation IDs are required")
        aware(asof, "valuation.asof")
        if not isinstance(marks, Mapping):
            raise StoreError("marks must map codes to prices")
        clean: dict[str, Decimal] = {}
        for code, price in marks.items():
            if not isinstance(code, str) or not code:
                raise StoreError("mark code must be nonempty text")
            clean[code] = money(price, f"mark[{code}]", positive=True)
        payload = _json({"account_id": account_id, "expected_revision": expected_revision,
                         "valuation_id": valuation_id, "asof": asof.isoformat(),
                         "marks": {code: str(clean[code]) for code in sorted(clean)}})

        def action(db: sqlite3.Connection) -> str:
            prior = db.execute("SELECT * FROM valuations WHERE valuation_id=?", (valuation_id,)).fetchone()
            if prior:
                if prior["payload"] != payload or prior["payload_hash"] != _hash(payload):
                    raise StoreError("valuation ID has a different payload")
                return prior["resulting_revision"]
            account = db.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
            if account is None:
                raise StoreError("unknown account")
            if account["revision"] != expected_revision:
                raise StoreError("stale account revision")
            positions = db.execute("SELECT code,quantity FROM positions WHERE account_id=?",
                                   (account_id,)).fetchall()
            held = {row["code"]: row["quantity"] for row in positions}
            if set(clean) != set(held):
                raise StoreError("marks must cover exactly the held codes")
            try:
                equity = Decimal(account["available_cash"]) + sum(
                    (Decimal(qty) * clean[code] for code, qty in held.items()), Decimal(0))
            except ArithmeticError as exc:
                raise StoreError("valuation arithmetic overflow") from exc
            if not equity.is_finite():
                raise StoreError("valuation equity is nonfinite")
            count = account["revision_count"] + 1
            revision = f"{account['base_revision']}#{count}"
            needs_reconcile = int(account["reconciliation_required"] or equity <= 0 or
                                  Decimal(account["available_cash"]) < 0)
            db.execute("UPDATE accounts SET revision=?, revision_count=?, equity=?, reconciliation_required=? WHERE account_id=?",
                       (revision, count, str(equity), needs_reconcile, account_id))
            db.execute("INSERT INTO valuations VALUES(?,?,?,?,?)",
                       (valuation_id, account_id, payload, _hash(payload), revision))
            return revision

        return self._write(action)

    def order_status(self, intent_id: str) -> str:
        with self._connect() as db:
            row = db.execute("SELECT status FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
            if row is None:
                raise StoreError("unknown intent")
            return row["status"]

    def account_view(self, account_id: str) -> dict[str, Any]:
        """Read a detached snapshot; negative actual cash signals reconciliation."""
        with self._connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
            if row is None:
                raise StoreError("unknown account")
            positions = {p["code"]: {"quantity": p["quantity"], "average_cost": p["average_cost"]}
                         for p in db.execute("SELECT * FROM positions WHERE account_id=? ORDER BY code", (account_id,))}
            db.commit()
            return {"account_id": account_id, "revision": row["revision"],
                    "equity": row["equity"], "available_cash": row["available_cash"],
                    "positions": positions, "reconciliation_required": bool(row["reconciliation_required"])}

    def recovery_required(self) -> tuple[str, ...]:
        """Uncertain intents needing broker-side reconciliation before retry."""
        with self._connect() as db:
            return tuple(r["intent_id"] for r in db.execute(
                "SELECT intent_id FROM orders WHERE status IN ('SUBMITTING','UNKNOWN') ORDER BY intent_id"))

    def export_view(self, *, failure_hook: Callable[[str], None] | None = None) -> dict[str, Any]:
        """Detached JSON-compatible view; export failure never changes the journal."""
        with self._connect() as db:
            db.execute("BEGIN")  # one consistent WAL/read snapshot for all tables
            view = {
                "run_evidence": [dict(row) for row in db.execute("SELECT * FROM run_evidence ORDER BY run_id")],
                "runs": [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY run_id")],
                "orders": [dict(row) for row in db.execute("SELECT * FROM orders ORDER BY intent_id")],
                "events": [dict(row) for row in db.execute("SELECT * FROM events ORDER BY event_id")],
                "fills": [dict(row) for row in db.execute("SELECT * FROM fills ORDER BY trade_id")],
                "reconciliations": [dict(row) for row in db.execute("SELECT * FROM reconciliations ORDER BY evidence_ref")],
                "valuations": [dict(row) for row in db.execute("SELECT * FROM valuations ORDER BY valuation_id")],
            }
            db.commit()
        if failure_hook:
            failure_hook("after_read")
        return view
