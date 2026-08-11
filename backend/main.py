"""
Phase 4 - FastAPI backend. Serves the deduped data from Phase 1's tables
plus a manual /api/refresh that runs Phase 3's exact sync loop.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import poller
from config import settings

_conn_lock = threading.Lock()


def get_conn() -> sqlite3.Connection:
    return app.state.conn


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect(settings.database.path)
    db.init_db(conn)
    app.state.conn = conn

    # Background sync loop - runs for the life of the process. Silent (skips)
    # when Tally is closed; picks up automatically the next poll after Tally
    # opens. Same run_sync_cycle() as POST /api/refresh - one sync code path.
    stop_event = threading.Event()

    def _background_loop() -> None:
        while not stop_event.is_set():
            try:
                poller.run_sync_cycle(conn)
            except Exception as e:
                print(f"[poller] sync cycle failed: {e}")
            stop_event.wait(settings.polling.interval_minutes * 60)

    thread = threading.Thread(target=_background_loop, daemon=True)
    thread.start()

    yield

    stop_event.set()
    conn.close()


app = FastAPI(title="Tally Live Entity Dashboard", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return {k: row[k] for k in row.keys()} if row is not None else None


def latest_sync_status(conn: sqlite3.Connection) -> tuple[bool, Optional[str]]:
    row = conn.execute(
        "SELECT tally_reachable, taken_at FROM snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return False, None
    return bool(row["tally_reachable"]), row["taken_at"]


def envelope(conn: sqlite3.Connection, data) -> dict:
    reachable, last_synced_at = latest_sync_status(conn)
    return {
        "tally_reachable": reachable, "last_synced_at": last_synced_at,
        "company_name": settings.tally.company_name, "data": data,
    }


# ---------------------------------------------------------------------------
# GET /api/overview
# ---------------------------------------------------------------------------

@app.get("/api/overview")
def get_overview():
    conn = get_conn()
    with _conn_lock:
        total_receivables = conn.execute(
            "SELECT COALESCE(SUM(current_balance), 0) v FROM entities WHERE entity_type = 'customer'"
        ).fetchone()["v"]
        total_payables = conn.execute(
            "SELECT COALESCE(SUM(current_balance), 0) v FROM entities WHERE entity_type = 'vendor'"
        ).fetchone()["v"]
        entity_count = conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]
        overdue_entity_count = conn.execute(
            "SELECT COUNT(DISTINCT entity_id) c FROM bills WHERE status = 'overdue'"
        ).fetchone()["c"]

        data = {
            "total_receivables": total_receivables,
            "total_payables": total_payables,
            "net_position": total_receivables - total_payables,
            "entity_count": entity_count,
            "overdue_entity_count": overdue_entity_count,
        }
        return envelope(conn, data)


# ---------------------------------------------------------------------------
# GET /api/entities
# ---------------------------------------------------------------------------

@app.get("/api/entities")
def get_entities(
    type: Optional[str] = None,
    search: Optional[str] = None,
    sort: Optional[str] = "name_asc",
    overdue_only: bool = False,
):
    conn = get_conn()
    with _conn_lock:
        query = """
            SELECT e.*,
                (SELECT COUNT(*) FROM bills b WHERE b.entity_id = e.id AND b.status = 'open') AS open_bill_count,
                (SELECT COUNT(*) FROM bills b WHERE b.entity_id = e.id AND b.status = 'overdue') AS overdue_bill_count
            FROM entities e
            WHERE 1=1
        """
        params: list = []
        if type:
            query += " AND e.entity_type = ?"
            params.append(type)
        if search:
            query += " AND LOWER(e.tally_ledger_name) LIKE LOWER(?)"
            params.append(f"%{search}%")

        rows = conn.execute(query, params).fetchall()

        items = [{
            "id": r["id"], "name": r["tally_ledger_name"], "type": r["entity_type"],
            "current_balance": r["current_balance"], "balance_type": r["balance_type"],
            "open_bill_count": r["open_bill_count"], "overdue_bill_count": r["overdue_bill_count"],
            "last_changed_at": r["last_changed_at"],
        } for r in rows]

        if overdue_only:
            items = [i for i in items if i["overdue_bill_count"] > 0]

        if sort == "balance_desc":
            items.sort(key=lambda i: i["current_balance"] or 0, reverse=True)
        else:  # name_asc default
            items.sort(key=lambda i: (i["name"] or "").lower())

        return envelope(conn, items)


# ---------------------------------------------------------------------------
# GET /api/entities/{id}
# ---------------------------------------------------------------------------

@app.get("/api/entities/{entity_id}")
def get_entity_detail(entity_id: int):
    conn = get_conn()
    with _conn_lock:
        entity = db.get_entity(conn, entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Entity not found")

        open_count, overdue_count = db.count_open_overdue_bills(conn, entity_id)
        entity_data = {
            "id": entity["id"], "name": entity["tally_ledger_name"], "type": entity["entity_type"],
            "current_balance": entity["current_balance"], "balance_type": entity["balance_type"],
            "open_bill_count": open_count, "overdue_bill_count": overdue_count,
            "last_changed_at": entity["last_changed_at"],
        }

        bills = [{
            "bill_ref": b["bill_ref"], "bill_date": b["bill_date"], "due_date": b["due_date"],
            "original_amount": b["original_amount"], "amount_outstanding": b["amount_outstanding"],
            "status": b["status"],
        } for b in db.list_bills_for_entity(conn, entity_id)]

        history_rows = conn.execute(
            """
            SELECT s.taken_at, seb.balance, seb.balance_type
            FROM snapshot_entity_balances seb
            JOIN snapshots s ON s.id = seb.snapshot_id
            WHERE seb.entity_id = ?
            ORDER BY s.taken_at ASC
            """,
            (entity_id,),
        ).fetchall()
        balance_history = [{"taken_at": h["taken_at"], "balance": h["balance"]} for h in history_rows]

        followups = [{
            "id": f["id"], "note": f["note"], "status": f["status"], "created_at": f["created_at"],
        } for f in db.list_followups(conn, entity_id)]

        data = {"entity": entity_data, "bills": bills, "balance_history": balance_history, "followups": followups}
        return envelope(conn, data)


# ---------------------------------------------------------------------------
# POST /api/entities/{id}/followup
# ---------------------------------------------------------------------------

class FollowupIn(BaseModel):
    note: str
    status: str = "pending"


@app.post("/api/entities/{entity_id}/followup")
def post_followup(entity_id: int, body: FollowupIn):
    conn = get_conn()
    with _conn_lock:
        entity = db.get_entity(conn, entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        row = db.add_followup(conn, entity_id, body.note, body.status)
        conn.commit()
        return row_to_dict(row)


# ---------------------------------------------------------------------------
# GET /api/stock
# ---------------------------------------------------------------------------

@app.get("/api/stock")
def get_stock(low_stock_only: bool = False):
    conn = get_conn()
    with _conn_lock:
        threshold = settings.stock.low_stock_threshold
        rows = db.list_stock_items(conn)
        items = [{
            "item_name": r["item_name"], "qty": r["qty"], "unit": r["unit"], "value": r["value"],
            "low_stock": r["qty"] <= threshold,
        } for r in rows]
        if low_stock_only:
            items = [i for i in items if i["low_stock"]]
        return envelope(conn, items)


# ---------------------------------------------------------------------------
# GET /api/changes
# ---------------------------------------------------------------------------

@app.get("/api/changes")
def get_changes(since: Optional[str] = None, limit: int = 50):
    conn = get_conn()
    with _conn_lock:
        rows = db.list_changes(conn, since=since, limit=limit)
        items = [{
            "id": r["id"], "change_type": r["change_type"], "message": r["message"],
            "detected_at": r["detected_at"],
        } for r in rows]
        return envelope(conn, items)


# ---------------------------------------------------------------------------
# POST /api/refresh
# ---------------------------------------------------------------------------

@app.post("/api/refresh")
def post_refresh():
    conn = get_conn()
    with _conn_lock:
        result = poller.run_sync_cycle(conn)
        return {
            "tally_reachable": result["tally_reachable"],
            "last_synced_at": result["last_synced_at"],
            "changes_detected": result["changes_detected"],
        }


# ---------------------------------------------------------------------------
# Static frontend (Phase 5) - mounted last so it doesn't shadow /api routes
# ---------------------------------------------------------------------------

_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
