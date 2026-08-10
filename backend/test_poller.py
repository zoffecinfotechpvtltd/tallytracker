"""
Phase 3 verification - offline simulation.

This proves the sync/diff logic itself is idempotent using a FAKE Tally
client (no real Tally needed), by monkeypatching tally_client's fetch
functions. This is a stand-in for the Master Prompt's Phase 3 checklist,
which additionally requires running the exact same 3x-in-a-row +
one-real-edit sequence against your REAL Tally (do that separately once
Phase 2's test_tally_client.py is green against your live data - the
db/diff logic exercised here is identical either way).

Run: python test_poller.py
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import db
import poller
import tally_client

TEST_DB_PATH = "test_phase3.db"

FAKE_TB = [
    {"ledger_name": "ABC Traders", "balance": 15000.0, "balance_type": "Dr"},
    {"ledger_name": "XYZ Supplies", "balance": 8000.0, "balance_type": "Cr"},
]
FAKE_BILLS_R = [
    {"ledger_name": "ABC Traders", "bill_ref": "INV-001", "bill_date": None, "due_date": None,
     "original_amount": 15000.0, "amount_outstanding": 15000.0},
]
FAKE_BILLS_P = [
    {"ledger_name": "XYZ Supplies", "bill_ref": "PB-001", "bill_date": None, "due_date": None,
     "original_amount": 8000.0, "amount_outstanding": 8000.0},
]
FAKE_STOCK = [
    {"item_name": "Widget A", "qty": 100.0, "unit": "pcs", "value": 10000.0},
]


def check(label: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        raise SystemExit(1)


def main() -> None:
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    conn = db.connect(TEST_DB_PATH)
    db.init_db(conn)

    tally_client.check_tally_alive = lambda timeout_s=2.5: True
    tally_client.fetch_trial_balance = lambda: list(FAKE_TB)
    tally_client.fetch_bills_receivable = lambda: list(FAKE_BILLS_R)
    tally_client.fetch_bills_payable = lambda: list(FAKE_BILLS_P)
    tally_client.fetch_stock_summary = lambda: list(FAKE_STOCK)

    def row_counts():
        return (
            conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"],
            conn.execute("SELECT COUNT(*) c FROM bills").fetchone()["c"],
            conn.execute("SELECT COUNT(*) c FROM stock_items").fetchone()["c"],
        )

    # Run 1
    r1 = poller.run_sync_cycle(conn)
    check("run 1: tally_reachable True", r1["tally_reachable"] is True)
    counts1 = row_counts()
    check("run 1: entities/bills/stock populated", counts1 == (2, 2, 1))

    # Run 2 - identical Tally state
    r2 = poller.run_sync_cycle(conn)
    counts2 = row_counts()
    check("run 2: row counts unchanged", counts2 == counts1)
    check("run 2: zero new changes rows", r2["changes_detected"] == 0)

    # Run 3 - proves idempotency, not a fluke
    r3 = poller.run_sync_cycle(conn)
    counts3 = row_counts()
    check("run 3: row counts unchanged", counts3 == counts1)
    check("run 3: zero new changes rows", r3["changes_detected"] == 0)

    # Now make ONE real edit: bump ABC Traders' balance
    FAKE_TB[0] = {"ledger_name": "ABC Traders", "balance": 20000.0, "balance_type": "Dr"}
    r4 = poller.run_sync_cycle(conn)
    counts4 = row_counts()
    check("after edit: entity/bill/stock row counts still unchanged (upsert, not insert)", counts4 == counts1)
    check("after edit: exactly ONE change row", r4["changes_detected"] == 1)

    changes = conn.execute(
        "SELECT * FROM changes WHERE snapshot_id = ?", (r4["snapshot_id"],)
    ).fetchall()
    check("exactly one row in changes table for this snapshot", len(changes) == 1)
    msg = changes[0]["message"]
    check(f"message mentions the right entity and direction (got: {msg!r})",
          "ABC Traders" in msg and "increased" in msg)

    conn.close()
    os.remove(TEST_DB_PATH)
    print("\nAll Phase 3 offline simulation checks passed.")
    print("NOTE: also run this exact 3x-plus-one-edit sequence against your REAL Tally")
    print("per the Master Prompt's Phase 3 checklist before moving on with confidence.")


if __name__ == "__main__":
    main()
