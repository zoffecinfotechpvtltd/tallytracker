"""
Phase 4 verification - offline, using FastAPI's TestClient + a fake Tally
client (same monkeypatch pattern as test_poller.py). No real Tally needed
for these structural checks; still run the app for real against your
live Tally afterwards (uvicorn main:app) to sanity check end to end.

Run: python test_api.py
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TEST_DB_PATH = "test_phase4.db"
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)

import config
config.settings.database.path = TEST_DB_PATH

import tally_client

FAKE_TB = [
    {"ledger_name": "ABC Traders", "balance": 15000.0, "balance_type": "Dr"},
    {"ledger_name": "XYZ Supplies", "balance": 8000.0, "balance_type": "Cr"},
]
FAKE_BILLS_R = [
    {"ledger_name": "ABC Traders", "bill_ref": "INV-001", "bill_date": None, "due_date": None,
     "original_amount": 15000.0, "amount_outstanding": 15000.0},
]
FAKE_BILLS_P: list = []
FAKE_STOCK = [
    {"item_name": "Widget A", "qty": 100.0, "unit": "pcs", "value": 10000.0},
]

_tally_alive = True
tally_client.check_tally_alive = lambda timeout_s=2.5: _tally_alive
tally_client.fetch_trial_balance = lambda: list(FAKE_TB)
tally_client.fetch_bills_receivable = lambda: list(FAKE_BILLS_R)
tally_client.fetch_bills_payable = lambda: list(FAKE_BILLS_P)
tally_client.fetch_stock_summary = lambda: list(FAKE_STOCK)

from fastapi.testclient import TestClient
from main import app


def check(label: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        raise SystemExit(1)


def main() -> None:
    with TestClient(app) as client:
        r = client.post("/api/refresh")
        check("POST /api/refresh returns 200", r.status_code == 200)
        body = r.json()
        check("refresh: tally_reachable True", body["tally_reachable"] is True)
        check("refresh: changes_detected present", "changes_detected" in body)

        r = client.get("/api/entities")
        check("GET /api/entities returns 200", r.status_code == 200)
        entities = r.json()["data"]
        conn = app.state.conn
        db_count = conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]
        check("entities endpoint row count == SELECT COUNT(*) FROM entities", len(entities) == db_count)
        check("each entity appears exactly once (no dup names)",
              len({e["name"] for e in entities}) == len(entities))

        r = client.get("/api/overview")
        check("GET /api/overview returns 200", r.status_code == 200)
        overview = r.json()["data"]
        check("overview has expected keys", set(overview.keys()) == {
            "total_receivables", "total_payables", "net_position", "entity_count", "overdue_entity_count",
        })

        r = client.get("/api/stock")
        check("GET /api/stock returns 200", r.status_code == 200)

        r = client.get("/api/changes")
        check("GET /api/changes returns 200", r.status_code == 200)

        entity_id = entities[0]["id"]
        r = client.get(f"/api/entities/{entity_id}")
        check("GET /api/entities/{id} returns 200", r.status_code == 200)
        detail = r.json()["data"]
        check("entity detail has bills/balance_history/followups", set(detail.keys()) >= {
            "entity", "bills", "balance_history", "followups",
        })

        r = client.post(f"/api/entities/{entity_id}/followup", json={
            "note": "Called, promised payment by Friday", "status": "contacted",
        })
        check("POST followup returns 200", r.status_code == 200)
        check("followup note echoed back", r.json()["note"] == "Called, promised payment by Friday")

        # Kill Tally -> GET should still be 200 with tally_reachable False and last-known-good data
        global _tally_alive
        _tally_alive = False
        r = client.post("/api/refresh")
        check("refresh with Tally down returns 200 (not 500)", r.status_code == 200)
        check("refresh with Tally down reports tally_reachable False", r.json()["tally_reachable"] is False)

        r = client.get("/api/entities")
        check("GET after Tally down still returns 200", r.status_code == 200)
        payload = r.json()
        check("envelope reports tally_reachable False", payload["tally_reachable"] is False)
        check("last-known-good data still served (not empty)", len(payload["data"]) == db_count)

    os.remove(TEST_DB_PATH)
    print("\nAll Phase 4 checks passed.")


if __name__ == "__main__":
    main()
