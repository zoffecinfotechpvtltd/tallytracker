"""
Phase 3 - diff engine. Compares a snapshot against the one immediately
before it and writes exactly one `changes` row per detected difference.
Notifier is called exactly once per change written here - never once per
poll - so a no-op poll fires zero notifications.
"""
from __future__ import annotations

import sqlite3

import db
import notifier


def _signed(balance: float, balance_type: str | None) -> float:
    return balance if balance_type == "Dr" else -balance


def compute_changes(
    conn: sqlite3.Connection,
    prev_snapshot: sqlite3.Row | None,
    curr_snapshot: sqlite3.Row,
    stock_deltas: list[dict],
) -> list[sqlite3.Row]:
    changes: list[sqlite3.Row] = []
    curr_taken_at = curr_snapshot["taken_at"]

    # --- balance_change ---
    if prev_snapshot is not None:
        curr_balances = conn.execute(
            "SELECT * FROM snapshot_entity_balances WHERE snapshot_id = ?", (curr_snapshot["id"],)
        ).fetchall()
        for cb in curr_balances:
            prev_bal = db.get_snapshot_entity_balance(conn, prev_snapshot["id"], cb["entity_id"])
            if prev_bal is None:
                continue  # newly discovered this poll - onboarding, not a change
            if cb["balance"] != prev_bal["balance"] or cb["balance_type"] != prev_bal["balance_type"]:
                entity = db.get_entity(conn, cb["entity_id"])
                old_signed = _signed(prev_bal["balance"], prev_bal["balance_type"])
                new_signed = _signed(cb["balance"], cb["balance_type"])
                delta = new_signed - old_signed
                direction = "increased" if delta > 0 else "decreased"
                message = f"{entity['tally_ledger_name']} balance {direction} by ₹{abs(delta):,.2f}"
                row = db.write_change(
                    conn, curr_snapshot["id"], "balance_change", message,
                    entity_id=entity["id"], old_value=old_signed, new_value=new_signed, delta=delta,
                )
                changes.append(row)
                notifier.notify(row)

    # --- new_bill: bills first seen exactly this poll ---
    new_bills = conn.execute(
        "SELECT * FROM bills WHERE first_seen_at = ?", (curr_taken_at,)
    ).fetchall()
    for bill in new_bills:
        entity = db.get_entity(conn, bill["entity_id"])
        message = (
            f"New bill from {entity['tally_ledger_name']}: {bill['bill_ref']} "
            f"(₹{(bill['original_amount'] or 0):,.2f})"
        )
        row = db.write_change(
            conn, curr_snapshot["id"], "new_bill", message,
            entity_id=entity["id"], new_value=bill["original_amount"],
        )
        changes.append(row)
        notifier.notify(row)

    # --- bill_settled: bills closed exactly this poll ---
    settled_bills = conn.execute(
        "SELECT * FROM bills WHERE status = 'closed' AND last_seen_at = ?", (curr_taken_at,)
    ).fetchall()
    for bill in settled_bills:
        entity = db.get_entity(conn, bill["entity_id"])
        message = f"{entity['tally_ledger_name']} settled bill {bill['bill_ref']}"
        row = db.write_change(
            conn, curr_snapshot["id"], "bill_settled", message,
            entity_id=entity["id"], old_value=bill["amount_outstanding"], new_value=0,
        )
        changes.append(row)
        notifier.notify(row)

    # --- stock_change: qty deltas captured by the poller within this poll call ---
    for d in stock_deltas:
        message = f"{d['item_name']} stock changed from {d['old_qty']} to {d['new_qty']} {d['unit'] or ''}".strip()
        row = db.write_change(
            conn, curr_snapshot["id"], "stock_change", message,
            stock_item_id=d["item_id"], old_value=d["old_qty"], new_value=d["new_qty"],
            delta=d["new_qty"] - d["old_qty"],
        )
        changes.append(row)
        notifier.notify(row)

    return changes
