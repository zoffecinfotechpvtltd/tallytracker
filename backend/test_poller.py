"""
Phase 3 tests - offline simulation.

Proves the sync/diff logic itself is idempotent using a FAKE Tally client
(no real Tally needed), by monkeypatching tally_client's fetch functions.
This is a stand-in for the Master Prompt's Phase 3 checklist, which
additionally requires running the exact same 3x-in-a-row + one-real-edit
sequence against your REAL Tally (do that separately via
`verify_live_tally.py` against your live data - the db/diff logic
exercised here is identical either way).

Run: pytest test_poller.py
"""
import sqlite3

import pytest

import db
import poller


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


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = db.connect(str(tmp_path / "test_phase3.db"))
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture()
def fake_tally(monkeypatch):
    """Fresh copies each test so mutating FAKE_TB in one test can't leak into another."""
    tb = [dict(row) for row in FAKE_TB]
    monkeypatch.setattr(poller.tally_client, "check_tally_alive", lambda timeout_s=2.5: True)
    monkeypatch.setattr(poller.tally_client, "fetch_trial_balance", lambda: list(tb))
    monkeypatch.setattr(poller.tally_client, "fetch_bills_receivable", lambda: [dict(r) for r in FAKE_BILLS_R])
    monkeypatch.setattr(poller.tally_client, "fetch_bills_payable", lambda: [dict(r) for r in FAKE_BILLS_P])
    monkeypatch.setattr(poller.tally_client, "fetch_stock_summary", lambda: [dict(r) for r in FAKE_STOCK])
    return tb


def _row_counts(conn):
    return (
        conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"],
        conn.execute("SELECT COUNT(*) c FROM bills").fetchone()["c"],
        conn.execute("SELECT COUNT(*) c FROM stock_items").fetchone()["c"],
    )


def test_sync_cycle_idempotent_then_detects_real_change(conn, fake_tally):
    tb = fake_tally

    r1 = poller.run_sync_cycle(conn)
    assert r1["tally_reachable"] is True
    counts1 = _row_counts(conn)
    assert counts1 == (2, 2, 1)

    # identical Tally state, twice more - must not duplicate or falsely detect changes
    r2 = poller.run_sync_cycle(conn)
    assert _row_counts(conn) == counts1
    assert r2["changes_detected"] == 0

    r3 = poller.run_sync_cycle(conn)
    assert _row_counts(conn) == counts1
    assert r3["changes_detected"] == 0

    # one real edit: bump ABC Traders' balance
    tb[0] = {"ledger_name": "ABC Traders", "balance": 20000.0, "balance_type": "Dr"}
    r4 = poller.run_sync_cycle(conn)
    assert _row_counts(conn) == counts1  # upsert, not insert
    assert r4["changes_detected"] == 1

    changes = conn.execute(
        "SELECT * FROM changes WHERE snapshot_id = ?", (r4["snapshot_id"],)
    ).fetchall()
    assert len(changes) == 1
    msg = changes[0]["message"]
    assert "ABC Traders" in msg and "increased" in msg
