"""
Phase 4 - FastAPI backend. Serves the deduped data from Phase 1's tables
plus a manual /api/refresh that runs Phase 3's exact sync loop.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import bank_reconciliation
import db
import poller
import tally_client
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


def envelope(conn: sqlite3.Connection, data, **extra) -> dict:
    reachable, last_synced_at = latest_sync_status(conn)
    result = {
        "tally_reachable": reachable, "last_synced_at": last_synced_at,
        "company_name": settings.tally.company_name, "data": data,
    }
    result.update(extra)
    return result


def _paginate(items: list, page: int, page_size: int) -> tuple[list, int]:
    page = max(page, 1)
    page_size = max(page_size, 1)
    start = (page - 1) * page_size
    return items[start:start + page_size], len(items)


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

_ENTITY_SORT_KEYS = {
    "name": lambda i: (i["name"] or "").lower(),
    "type": lambda i: (i["type"] or "").lower(),
    "balance": lambda i: i["current_balance"] or 0,
    "open_bills": lambda i: i["open_bill_count"] or 0,
    "overdue_bills": lambda i: i["overdue_bill_count"] or 0,
    "last_changed": lambda i: i["last_changed_at"] or "",
}


@app.get("/api/entities")
def get_entities(
    type: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "name",
    sort_dir: str = "asc",
    overdue_only: bool = False,
    page: int = 1,
    page_size: int = 50,
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

        key_fn = _ENTITY_SORT_KEYS.get(sort_by, _ENTITY_SORT_KEYS["name"])
        items.sort(key=key_fn, reverse=(sort_dir == "desc"))

        page_items, total = _paginate(items, page, page_size)
        return envelope(conn, page_items, total=total, page=page, page_size=page_size)


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
# GET /api/entities/{id}/vouchers - live from Tally, not synced/stored, so the
# 5-minute poll stays fast and we don't accumulate years of transaction history
# for entities nobody looks at.
# ---------------------------------------------------------------------------

@app.get("/api/entities/{entity_id}/vouchers")
def get_entity_vouchers(entity_id: int):
    conn = get_conn()
    with _conn_lock:
        entity = db.get_entity(conn, entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        ledger_name = entity["tally_ledger_name"]

    try:
        vouchers = tally_client.fetch_vouchers_for_ledger(ledger_name)
        reachable = True
    except tally_client.TallyUnreachableError:
        vouchers = []
        reachable = False

    data = [{
        "date": v["date"].isoformat() if v["date"] else None,
        "voucher_type": v["voucher_type"],
        "voucher_number": v["voucher_number"],
        "amount": v["amount"],
        "narration": v["narration"],
    } for v in vouchers]
    return {"tally_reachable": reachable, "data": data}


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

_STOCK_SORT_KEYS = {
    "item_name": lambda i: (i["item_name"] or "").lower(),
    "qty": lambda i: i["qty"] or 0,
    "unit": lambda i: (i["unit"] or "").lower(),
    "value": lambda i: i["value"] or 0,
}


@app.get("/api/stock")
def get_stock(
    low_stock_only: bool = False, sort_by: str = "item_name", sort_dir: str = "asc",
    page: int = 1, page_size: int = 50,
):
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
        key_fn = _STOCK_SORT_KEYS.get(sort_by, _STOCK_SORT_KEYS["item_name"])
        items.sort(key=key_fn, reverse=(sort_dir == "desc"))
        page_items, total = _paginate(items, page, page_size)
        return envelope(conn, page_items, total=total, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# GET /api/bills-due - flat "who/when/how much" lists for Payable and
# Receivable views. direction=payable -> vendors you owe; direction=
# receivable -> customers who owe you. Soonest due first.
# ---------------------------------------------------------------------------

_DIRECTION_TO_ENTITY_TYPE = {"payable": "vendor", "receivable": "customer"}

# "due" is the default: soonest-due-first with no-due-date bills sorted last -
# not just an ascending date sort (see list_bills_due) - so it gets its own key
# rather than falling out of a plain days_until_due sort (which would put
# unknown due dates first, backwards from what you'd want).
_BILLS_DUE_SORT_KEYS = {
    "entity_name": lambda i: (i["entity_name"] or "").lower(),
    "bill_ref": lambda i: (i["bill_ref"] or "").lower(),
    "bill_date": lambda i: i["bill_date"] or "",
    "due": lambda i: (i["days_until_due"] is None, i["days_until_due"]),
    "amount": lambda i: i["amount_outstanding"] or 0,
}


@app.get("/api/bills-due")
def get_bills_due(
    direction: str, sort_by: str = "due", sort_dir: str = "asc",
    page: int = 1, page_size: int = 50,
):
    if direction not in _DIRECTION_TO_ENTITY_TYPE:
        raise HTTPException(status_code=400, detail="direction must be 'payable' or 'receivable'")
    conn = get_conn()
    with _conn_lock:
        today = db.now_iso()[:10]
        rows = db.list_bills_due(conn, _DIRECTION_TO_ENTITY_TYPE[direction])
        items = []
        for r in rows:
            days_until_due = None
            if r["due_date"]:
                days_until_due = (date.fromisoformat(r["due_date"]) - date.fromisoformat(today)).days
            items.append({
                "entity_id": r["entity_id"], "entity_name": r["entity_name"],
                "bill_ref": r["bill_ref"], "bill_date": r["bill_date"], "due_date": r["due_date"],
                "amount_outstanding": r["amount_outstanding"], "status": r["status"],
                "days_until_due": days_until_due,
            })

        key_fn = _BILLS_DUE_SORT_KEYS.get(sort_by, _BILLS_DUE_SORT_KEYS["due"])
        items.sort(key=key_fn, reverse=(sort_dir == "desc"))

        total_amount = sum(i["amount_outstanding"] or 0 for i in items)
        overdue_count = sum(1 for i in items if i["days_until_due"] is not None and i["days_until_due"] < 0)
        page_items, total = _paginate(items, page, page_size)
        return envelope(
            conn, page_items, total=total, page=page, page_size=page_size,
            total_amount=total_amount, overdue_count=overdue_count,
        )


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
# GET /api/stream - Server-Sent Events. Pushes a "sync" event whenever a new
# snapshot appears (background timer OR /api/refresh, from any client), so the
# frontend refetches within ~2s of real data changing instead of waiting up to
# 30s of polling. Heartbeat comments keep the connection alive through proxies.
# ---------------------------------------------------------------------------

@app.get("/api/stream")
async def stream_updates():
    async def event_generator():
        last_snapshot_id = None
        while True:
            with _conn_lock:
                row = get_conn().execute(
                    "SELECT id FROM snapshots ORDER BY id DESC LIMIT 1"
                ).fetchone()
            current_id = row["id"] if row else None
            if current_id != last_snapshot_id:
                last_snapshot_id = current_id
                yield f"event: sync\ndata: {current_id}\n\n"
            else:
                yield ": heartbeat\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Bank reconciliation - upload an .xlsx bank statement, get fuzzy-matched
# suggestions against open bills. Nothing here ever touches Tally or a bill's
# status - purely local tracking, and a suggestion only becomes a real match
# once the user explicitly confirms it (see bank_reconciliation.py).
# ---------------------------------------------------------------------------

def _candidate_bills_for_match(conn: sqlite3.Connection, direction: str) -> list[dict]:
    # A credit into our bank account is a customer paying us (receivable);
    # a debit is us paying a vendor (payable).
    entity_type = "customer" if direction == "credit" else "vendor"
    rows = db.list_bills_due(conn, entity_type)
    return [{
        "entity_id": r["entity_id"], "entity_name": r["entity_name"], "bill_ref": r["bill_ref"],
        "amount_outstanding": r["amount_outstanding"],
        "due_date": date.fromisoformat(r["due_date"]) if r["due_date"] else None,
    } for r in rows]


@app.post("/api/reconciliation/upload")
async def upload_bank_statement(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        transactions = bank_reconciliation.parse_bank_statement(raw)
    except bank_reconciliation.BankStatementError as e:
        raise HTTPException(status_code=400, detail=str(e))

    conn = get_conn()
    with _conn_lock:
        statement = db.create_bank_statement(conn, file.filename or "statement.xlsx", len(transactions))
        candidates_by_direction = {
            "credit": _candidate_bills_for_match(conn, "credit"),
            "debit": _candidate_bills_for_match(conn, "debit"),
        }
        for txn in transactions:
            match = bank_reconciliation.match_transaction(
                txn["narration"], txn["amount"], txn["date"], candidates_by_direction[txn["direction"]],
            )
            db.add_bank_transaction(
                conn, statement["id"],
                txn["date"].isoformat() if txn["date"] else None,
                txn["narration"], txn["reference"], txn["amount"], txn["direction"],
                matched_entity_id=match["entity_id"] if match else None,
                matched_bill_ref=match["bill_ref"] if match else None,
                match_confidence=match["confidence"] if match else None,
            )
        conn.commit()
    return {"statement_id": statement["id"], "row_count": len(transactions)}


@app.get("/api/reconciliation/statements")
def list_bank_statements():
    conn = get_conn()
    with _conn_lock:
        rows = conn.execute("SELECT * FROM bank_statements ORDER BY id DESC").fetchall()
        return [row_to_dict(r) for r in rows]


@app.get("/api/reconciliation/statements/{statement_id}/transactions")
def get_statement_transactions(statement_id: int):
    conn = get_conn()
    with _conn_lock:
        rows = db.list_bank_transactions(conn, statement_id)
        return [row_to_dict(r) for r in rows]


class ConfirmMatchIn(BaseModel):
    entity_id: int
    bill_ref: str


@app.post("/api/reconciliation/transactions/{transaction_id}/confirm")
def confirm_bank_transaction_match(transaction_id: int, body: ConfirmMatchIn):
    conn = get_conn()
    with _conn_lock:
        if db.get_bank_transaction(conn, transaction_id) is None:
            raise HTTPException(status_code=404, detail="Transaction not found")
        if db.get_entity(conn, body.entity_id) is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        row = db.set_bank_transaction_match(conn, transaction_id, body.entity_id, body.bill_ref, "confirmed")
        conn.commit()
        return row_to_dict(row)


@app.post("/api/reconciliation/transactions/{transaction_id}/ignore")
def ignore_bank_transaction(transaction_id: int):
    conn = get_conn()
    with _conn_lock:
        if db.get_bank_transaction(conn, transaction_id) is None:
            raise HTTPException(status_code=404, detail="Transaction not found")
        row = db.set_bank_transaction_match(conn, transaction_id, None, None, "ignored")
        conn.commit()
        return row_to_dict(row)


# ---------------------------------------------------------------------------
# Static frontend (Phase 5) - mounted last so it doesn't shadow /api routes
# ---------------------------------------------------------------------------

_frontend_dist_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_frontend_dist_dir):
    app.mount("/", StaticFiles(directory=_frontend_dist_dir, html=True), name="frontend")
else:
    @app.get("/")
    def _frontend_not_built():
        raise HTTPException(
            status_code=503,
            detail="Frontend not built yet - run `npm install && npm run build` in the frontend/ directory.",
        )
