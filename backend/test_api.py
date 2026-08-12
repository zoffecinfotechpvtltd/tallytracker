"""
Phase 4 tests - offline, using FastAPI's TestClient + a fake Tally client
(same monkeypatch pattern as test_poller.py). No real Tally needed for
these structural checks; still run the app for real against your live
Tally afterwards (uvicorn main:app) to sanity check end to end.

Run: pytest test_api.py
"""
import pytest
from fastapi.testclient import TestClient

import config
import tally_client
from main import app

FAKE_TB = [
    {"ledger_name": "ABC Traders", "balance": 15000.0, "balance_type": "Dr"},
    {"ledger_name": "XYZ Supplies", "balance": 8000.0, "balance_type": "Cr"},
]
FAKE_BILLS_R = [
    {"ledger_name": "ABC Traders", "bill_ref": "INV-001", "bill_date": None, "due_date": None,
     "original_amount": 15000.0, "amount_outstanding": 15000.0},
]
FAKE_STOCK = [
    {"item_name": "Widget A", "qty": 100.0, "unit": "pcs", "value": 10000.0},
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings.database, "path", str(tmp_path / "test_phase4.db"))

    alive = {"value": True}
    monkeypatch.setattr(tally_client, "check_tally_alive", lambda timeout_s=2.5: alive["value"])
    monkeypatch.setattr(tally_client, "fetch_trial_balance", lambda: list(FAKE_TB))
    monkeypatch.setattr(tally_client, "fetch_bills_receivable", lambda: [dict(r) for r in FAKE_BILLS_R])
    monkeypatch.setattr(tally_client, "fetch_bills_payable", lambda: [])
    monkeypatch.setattr(tally_client, "fetch_stock_summary", lambda: list(FAKE_STOCK))

    with TestClient(app) as c:
        c.tally_alive = alive  # type: ignore[attr-defined]
        yield c


def test_api_end_to_end(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["database_ok"] is True

    r = client.post("/api/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["tally_reachable"] is True
    assert "changes_detected" in body

    r = client.get("/api/entities")
    assert r.status_code == 200
    entities = r.json()["data"]
    conn = app.state.conn
    db_count = conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]
    assert len(entities) == db_count
    assert len({e["name"] for e in entities}) == len(entities)  # no dup names

    r = client.get("/api/overview")
    assert r.status_code == 200
    overview = r.json()["data"]
    assert set(overview.keys()) == {
        "total_receivables", "total_payables", "net_position", "entity_count", "overdue_entity_count",
    }

    assert client.get("/api/stock").status_code == 200
    assert client.get("/api/changes").status_code == 200

    entity_id = entities[0]["id"]
    r = client.get(f"/api/entities/{entity_id}")
    assert r.status_code == 200
    detail = r.json()["data"]
    assert set(detail.keys()) >= {"entity", "bills", "balance_history", "followups"}

    r = client.post(f"/api/entities/{entity_id}/followup", json={
        "note": "Called, promised payment by Friday", "status": "contacted",
    })
    assert r.status_code == 200
    assert r.json()["note"] == "Called, promised payment by Friday"

    # Kill Tally -> GET should still be 200 with tally_reachable False and last-known-good data
    client.tally_alive["value"] = False
    r = client.post("/api/refresh")
    assert r.status_code == 200  # not 500
    assert r.json()["tally_reachable"] is False

    r = client.get("/api/entities")
    assert r.status_code == 200
    payload = r.json()
    assert payload["tally_reachable"] is False
    assert len(payload["data"]) == db_count  # last-known-good data still served
