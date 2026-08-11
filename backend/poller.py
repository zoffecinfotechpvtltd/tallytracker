"""
Phase 3 - poll-and-diff loop. ONE function (`run_sync_cycle`) implements
the entire cycle from 03_SYNC_DIFF_ENGINE.md. It is called on a timer
(config-driven) and by POST /api/refresh - both paths call this exact
function, there is only one sync code path in the whole app.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date
from typing import Optional

import db
import diff_engine
import tally_client
from config import settings

_sync_lock = threading.Lock()

_EMPTY_RESULT_MAX_ATTEMPTS = 4
_EMPTY_RESULT_RETRY_DELAY_S = 3.0


def _fetch_all(poll_ts: str) -> tuple[list, list, list, list]:
    """Tally's ad-hoc XML export is intermittently flaky on some installs - the
    exact same request can come back with a full ledger list one moment and an
    empty (but well-formed, no error) collection the next, with no discernible
    trigger. A real trial balance being empty is implausible for a live
    company, so treat an all-empty trial balance as a signal to retry rather
    than as a true result."""
    for attempt in range(1, _EMPTY_RESULT_MAX_ATTEMPTS + 1):
        raw_tb = tally_client.fetch_trial_balance()
        raw_bills_r = tally_client.fetch_bills_receivable()
        raw_bills_p = tally_client.fetch_bills_payable()
        raw_stock = tally_client.fetch_stock_summary()
        if raw_tb or attempt == _EMPTY_RESULT_MAX_ATTEMPTS:
            if attempt > 1:
                print(f"[poller] {poll_ts} recovered on attempt {attempt}" if raw_tb
                      else f"[poller] {poll_ts} still empty after {attempt} attempts, giving up this cycle",
                      flush=True)
            return raw_tb, raw_bills_r, raw_bills_p, raw_stock
        print(f"[poller] {poll_ts} attempt {attempt} came back empty, retrying...", flush=True)
        time.sleep(_EMPTY_RESULT_RETRY_DELAY_S)
    raise AssertionError("unreachable")


def _iso_or_none(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d is not None else None


def resolve_entity(
    conn: sqlite3.Connection, poll_ts: str, ledger_name: str,
    entity_type: Optional[str] = None, balance: Optional[float] = None, balance_type: Optional[str] = None,
) -> sqlite3.Row:
    existing = db.get_entity_by_normalized_name(conn, ledger_name)
    bal = balance if balance is not None else (existing["current_balance"] if existing else 0.0)
    btype = balance_type if balance_type is not None else (existing["balance_type"] if existing else None)
    etype = entity_type if entity_type is not None else (existing["entity_type"] if existing else None)
    return db.upsert_entity(conn, ledger_name, etype, bal, btype, seen_at=poll_ts)


def resolve_bill(conn: sqlite3.Connection, poll_ts: str, entity_id: int, raw_bill: dict) -> sqlite3.Row:
    outstanding = raw_bill.get("amount_outstanding") or 0.0
    due_date = raw_bill.get("due_date")

    if raw_bill.get("bill_ref"):
        bill_ref = raw_bill["bill_ref"]
        confidence = "high"
    else:
        bill_ref = f"__fallback__{raw_bill.get('bill_date')}__{raw_bill.get('original_amount')}"
        confidence = "low"
        db.log_sync_error(
            conn, context="bill_match",
            raw_record=json.dumps({k: str(v) for k, v in raw_bill.items()}),
            reason="no bill_ref from Tally, used fallback key (entity_id, bill_date, original_amount)",
        )

    if outstanding <= 0:
        status = "closed"
    elif due_date is not None and due_date < date.today():
        status = "overdue"
    else:
        status = "open"

    return db.upsert_bill(
        conn, entity_id, bill_ref,
        _iso_or_none(raw_bill.get("bill_date")), _iso_or_none(due_date),
        raw_bill.get("original_amount"), outstanding, status, confidence, seen_at=poll_ts,
    )


def resolve_stock_item(conn: sqlite3.Connection, poll_ts: str, raw_item: dict) -> tuple[sqlite3.Row, Optional[float]]:
    existing = conn.execute(
        "SELECT qty FROM stock_items WHERE normalized_item_name = ?", (db.normalize(raw_item["item_name"]),)
    ).fetchone()
    old_qty = existing["qty"] if existing else None
    row = db.upsert_stock_item(
        conn, raw_item["item_name"], raw_item["qty"], raw_item.get("unit"), raw_item.get("value", 0.0),
        seen_at=poll_ts,
    )
    return row, old_qty


def run_sync_cycle(conn: sqlite3.Connection) -> dict:
    """Runs one full poll: fetch -> resolve (upsert, never blind-insert) -> snapshot ->
    diff vs. previous snapshot -> write `changes`. Thread-safe: concurrent callers
    (timer + manual /api/refresh) block on a lock rather than racing each other."""
    with _sync_lock:
        poll_ts = db.now_iso()

        if not tally_client.check_tally_alive():
            snap = db.create_snapshot(conn, tally_reachable=False, taken_at=poll_ts)
            conn.commit()
            return {
                "tally_reachable": False, "last_synced_at": snap["taken_at"],
                "changes_detected": 0, "snapshot_id": snap["id"],
            }

        try:
            raw_tb, raw_bills_r, raw_bills_p, raw_stock = _fetch_all(poll_ts)
            print(
                f"[poller] {poll_ts} fetched: trial_balance={len(raw_tb)} "
                f"bills_receivable={len(raw_bills_r)} bills_payable={len(raw_bills_p)} "
                f"stock={len(raw_stock)} company={settings.tally.company_name!r}",
                flush=True,
            )
        except tally_client.TallyUnreachableError as e:
            print(f"[poller] {poll_ts} TallyUnreachableError: {e}", flush=True)
            snap = db.create_snapshot(conn, tally_reachable=False, taken_at=poll_ts)
            conn.commit()
            return {
                "tally_reachable": False, "last_synced_at": snap["taken_at"],
                "changes_detected": 0, "snapshot_id": snap["id"],
            }

        try:
            entities: dict[int, sqlite3.Row] = {}
            for led in raw_tb:
                row = resolve_entity(
                    conn, poll_ts, led["ledger_name"],
                    balance=led["balance"], balance_type=led["balance_type"],
                )
                entities[row["id"]] = row

            bills_by_entity: dict[int, list[str]] = {}
            for bill in raw_bills_r:
                entity_row = resolve_entity(conn, poll_ts, bill["ledger_name"], entity_type="customer")
                entities.setdefault(entity_row["id"], entity_row)
                bill_row = resolve_bill(conn, poll_ts, entity_row["id"], bill)
                bills_by_entity.setdefault(entity_row["id"], []).append(bill_row["bill_ref"])
            for bill in raw_bills_p:
                entity_row = resolve_entity(conn, poll_ts, bill["ledger_name"], entity_type="vendor")
                entities.setdefault(entity_row["id"], entity_row)
                bill_row = resolve_bill(conn, poll_ts, entity_row["id"], bill)
                bills_by_entity.setdefault(entity_row["id"], []).append(bill_row["bill_ref"])

            for entity_id, refs in bills_by_entity.items():
                db.close_stale_bills(conn, entity_id, refs, poll_ts)

            stock_deltas = []
            for item in raw_stock:
                row, old_qty = resolve_stock_item(conn, poll_ts, item)
                if old_qty is not None and old_qty != row["qty"]:
                    stock_deltas.append({
                        "item_id": row["id"], "item_name": row["item_name"],
                        "unit": row["unit"], "old_qty": old_qty, "new_qty": row["qty"],
                    })

            snapshot = db.create_snapshot(conn, tally_reachable=True, taken_at=poll_ts)
            for entity_row in entities.values():
                fresh = db.get_entity(conn, entity_row["id"])
                db.write_snapshot_entity_balance(
                    conn, snapshot["id"], fresh["id"], fresh["current_balance"], fresh["balance_type"]
                )

            previous_snapshot = db.get_previous_snapshot(conn, snapshot["id"])
            changes = diff_engine.compute_changes(conn, previous_snapshot, snapshot, stock_deltas)

            conn.commit()
        except Exception:
            conn.rollback()
            raise

        return {
            "tally_reachable": True, "last_synced_at": snapshot["taken_at"],
            "changes_detected": len(changes), "snapshot_id": snapshot["id"],
        }


def run_forever(conn: sqlite3.Connection) -> None:
    """Background timer loop - default every settings.polling.interval_minutes."""
    import time
    while True:
        try:
            run_sync_cycle(conn)
        except Exception as e:
            print(f"[poller] sync cycle failed: {e}")
        time.sleep(settings.polling.interval_minutes * 60)
