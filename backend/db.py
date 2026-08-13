"""
Phase 1 - Data model & entity resolution primitives.

This is the ONLY module that runs raw SQL. Every other module (poller,
diff_engine, main/API) calls functions in here - never sqlite3 directly.

Dedup guarantee: entities / bills / stock_items each carry a real SQLite
UNIQUE constraint on their natural key, and every write is a single
`INSERT ... ON CONFLICT (...) DO UPDATE ...` statement. There is no
"check if exists, then insert" two-step path anywhere in this file.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    tally_ledger_name TEXT NOT NULL,
    normalized_ledger_name TEXT NOT NULL UNIQUE,
    entity_type TEXT CHECK(entity_type IN ('customer','vendor','other')),
    current_balance REAL NOT NULL DEFAULT 0,
    balance_type TEXT CHECK(balance_type IN ('Dr','Cr')),
    first_seen_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL,
    last_changed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bills (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    bill_ref TEXT NOT NULL,
    bill_date DATE,
    due_date DATE,
    original_amount REAL,
    amount_outstanding REAL,
    status TEXT CHECK(status IN ('open','overdue','closed')),
    match_confidence TEXT CHECK(match_confidence IN ('high','low')) DEFAULT 'high',
    first_seen_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL,
    UNIQUE(entity_id, bill_ref)
);

CREATE TABLE IF NOT EXISTS stock_items (
    id INTEGER PRIMARY KEY,
    item_name TEXT NOT NULL,
    normalized_item_name TEXT NOT NULL UNIQUE,
    qty REAL NOT NULL DEFAULT 0,
    unit TEXT,
    value REAL NOT NULL DEFAULT 0,
    last_seen_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    taken_at TIMESTAMP NOT NULL,
    tally_reachable BOOLEAN NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS snapshot_entity_balances (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    balance REAL NOT NULL,
    balance_type TEXT,
    PRIMARY KEY (snapshot_id, entity_id)
);

CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    entity_id INTEGER REFERENCES entities(id),
    stock_item_id INTEGER REFERENCES stock_items(id),
    change_type TEXT CHECK(change_type IN ('balance_change','new_bill','bill_settled','stock_change')),
    old_value REAL,
    new_value REAL,
    delta REAL,
    message TEXT NOT NULL,
    detected_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    note TEXT NOT NULL,
    status TEXT CHECK(status IN ('pending','contacted','resolved')) DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_errors (
    id INTEGER PRIMARY KEY,
    occurred_at TIMESTAMP NOT NULL,
    context TEXT,
    raw_record TEXT,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS bank_statements (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    uploaded_at TIMESTAMP NOT NULL,
    row_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bank_transactions (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES bank_statements(id),
    txn_date DATE,
    narration TEXT NOT NULL,
    reference TEXT,
    amount REAL NOT NULL,
    direction TEXT CHECK(direction IN ('credit','debit')) NOT NULL,
    matched_entity_id INTEGER REFERENCES entities(id),
    matched_bill_ref TEXT,
    match_confidence REAL,
    match_status TEXT CHECK(match_status IN ('unmatched','confirmed','ignored')) NOT NULL DEFAULT 'unmatched',
    confirmed_at TIMESTAMP
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def normalize(name: str) -> str:
    """Trim, collapse internal whitespace, case-fold. Used for entity/stock natural keys."""
    return re.sub(r"\s+", " ", name.strip()).casefold()


def connect(db_path: str) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI runs sync endpoints in a threadpool, so
    # requests can arrive on different threads. Safe here because main.py
    # serializes all access to this connection behind a single lock.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Numbered, one-way migrations. Each entry's script must be safe to run
# against a fresh DB. Migration 1 is the original `CREATE TABLE IF NOT
# EXISTS` schema (safe re-run on existing DBs with those tables already
# present) - it's what every install prior to this versioning scheme is
# grandfathered into. From here on, schema changes append a new
# (version, description, script) tuple instead of editing SCHEMA in place,
# so `python -m pip install -r requirements.txt && python run_server.py`
# after a `git pull` always leaves the DB in the shape the current code
# expects, with no manual ALTER TABLE required.
_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "baseline schema", SCHEMA),
    (2, "add bills.narration - what a bill was actually for, from the voucher", """
        ALTER TABLE bills ADD COLUMN narration TEXT;
    """),
]


def _current_schema_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        conn.commit()
        return 0
    return row["version"]


def _db_file_path(conn: sqlite3.Connection) -> Optional[str]:
    """The on-disk path sqlite opened this connection with, or None for an
    in-memory database (nothing to back up)."""
    row = conn.execute("PRAGMA database_list").fetchone()
    path = row["file"] if row else None
    return path or None


def backup_database(db_path: str, backup_dir: str, keep: int = 14, label: str = "") -> Optional[str]:
    """Copies db_path into backup_dir as a timestamped snapshot, then prunes
    down to the `keep` most recent backups. Returns the new backup's path, or
    None if db_path doesn't exist yet (nothing to protect)."""
    if not os.path.exists(db_path):
        return None
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    dest = os.path.join(backup_dir, f"tally{suffix}-{stamp}.db.bak")
    shutil.copy2(db_path, dest)

    backups = sorted(f for f in os.listdir(backup_dir) if f.startswith("tally") and f.endswith(".db.bak"))
    for old in backups[:-keep]:
        os.remove(os.path.join(backup_dir, old))
    return dest


def maybe_daily_backup(conn: sqlite3.Connection, keep: int = 14) -> Optional[str]:
    """Takes one backup per calendar day - safe to call on every poll cycle,
    it's a no-op once today's backup already exists."""
    db_path = _db_file_path(conn)
    if not db_path:
        return None
    backup_dir = os.path.join(os.path.dirname(db_path) or ".", "backups")
    today = datetime.now().strftime("%Y%m%d")
    if os.path.isdir(backup_dir) and any(f"-daily-{today}" in f for f in os.listdir(backup_dir)):
        return None
    return backup_database(db_path, backup_dir, keep=keep, label="daily")


def init_db(conn: sqlite3.Connection) -> None:
    current = _current_schema_version(conn)
    pending = [m for m in _MIGRATIONS if m[0] > current]

    # Back up before any real (non-baseline) migration touches an existing
    # database - `current > 0` means this DB has already been through the
    # versioning scheme at least once, so it's not a brand-new empty file.
    if pending and current > 0:
        db_path = _db_file_path(conn)
        if db_path:
            backup_database(db_path, os.path.join(os.path.dirname(db_path) or ".", "backups"), label="pre-migration")

    for version, _description, script in pending:
        conn.executescript(script)
        conn.execute("UPDATE schema_version SET version = ?", (version,))
        conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

def upsert_entity(
    conn: sqlite3.Connection,
    tally_ledger_name: str,
    entity_type: Optional[str],
    current_balance: float,
    balance_type: Optional[str],
    seen_at: Optional[str] = None,
) -> sqlite3.Row:
    seen_at = seen_at or now_iso()
    normalized = normalize(tally_ledger_name)
    row = conn.execute(
        """
        INSERT INTO entities (
            tally_ledger_name, normalized_ledger_name, entity_type,
            current_balance, balance_type, first_seen_at, last_seen_at, last_changed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(normalized_ledger_name) DO UPDATE SET
            tally_ledger_name = excluded.tally_ledger_name,
            entity_type = COALESCE(excluded.entity_type, entities.entity_type),
            current_balance = excluded.current_balance,
            balance_type = excluded.balance_type,
            last_seen_at = excluded.last_seen_at,
            last_changed_at = CASE
                WHEN entities.current_balance IS NOT excluded.current_balance
                  OR entities.balance_type IS NOT excluded.balance_type
                THEN excluded.last_seen_at
                ELSE entities.last_changed_at
            END
        RETURNING *
        """,
        (tally_ledger_name, normalized, entity_type, current_balance, balance_type, seen_at, seen_at, None),
    ).fetchone()
    return row


def get_entity_by_normalized_name(conn: sqlite3.Connection, raw_name: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM entities WHERE normalized_ledger_name = ?", (normalize(raw_name),)
    ).fetchone()


def get_entity(conn: sqlite3.Connection, entity_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()


def list_entities(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM entities ORDER BY tally_ledger_name").fetchall()


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------

def upsert_bill(
    conn: sqlite3.Connection,
    entity_id: int,
    bill_ref: str,
    bill_date: Optional[str],
    due_date: Optional[str],
    original_amount: Optional[float],
    amount_outstanding: Optional[float],
    status: str,
    match_confidence: str,
    seen_at: Optional[str] = None,
    narration: Optional[str] = None,
) -> sqlite3.Row:
    seen_at = seen_at or now_iso()
    row = conn.execute(
        """
        INSERT INTO bills (
            entity_id, bill_ref, bill_date, due_date, original_amount,
            amount_outstanding, status, match_confidence, first_seen_at, last_seen_at, narration
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_id, bill_ref) DO UPDATE SET
            bill_date = excluded.bill_date,
            due_date = excluded.due_date,
            original_amount = excluded.original_amount,
            amount_outstanding = excluded.amount_outstanding,
            status = excluded.status,
            match_confidence = excluded.match_confidence,
            last_seen_at = excluded.last_seen_at,
            narration = excluded.narration
        RETURNING *
        """,
        (entity_id, bill_ref, bill_date, due_date, original_amount, amount_outstanding,
         status, match_confidence, seen_at, seen_at, narration),
    ).fetchone()
    return row


def close_stale_bills(
    conn: sqlite3.Connection, entity_id: int, seen_bill_refs: list[str], seen_at: str,
    grace_cutoff: Optional[str] = None,
) -> list[sqlite3.Row]:
    """Mark as closed any open/overdue bill for this entity NOT present in this
    poll's bill list AND not present in the poll before that either. Never
    deletes rows - see 01_ARCHITECTURE_AND_DATA_MODEL.md 'Bill lifecycle'.

    Requires two consecutive misses (grace_cutoff = the previous successful
    poll's timestamp) before closing, not one: Tally's ad-hoc export has been
    observed to come back incomplete for a single cycle with no error, and
    closing on the first miss would misreport genuinely still-open bills as
    settled just because one poll happened to drop them."""
    if seen_bill_refs:
        placeholders = ",".join("?" for _ in seen_bill_refs)
        query = f"""
            SELECT * FROM bills
            WHERE entity_id = ? AND status IN ('open','overdue')
              AND bill_ref NOT IN ({placeholders})
        """
        params: list = [entity_id, *seen_bill_refs]
    else:
        query = "SELECT * FROM bills WHERE entity_id = ? AND status IN ('open','overdue')"
        params = [entity_id]

    if grace_cutoff is not None:
        query += " AND last_seen_at < ?"
        params.append(grace_cutoff)

    rows = conn.execute(query, params).fetchall()

    closed = []
    for r in rows:
        conn.execute(
            "UPDATE bills SET status = 'closed', last_seen_at = ? WHERE id = ?",
            (seen_at, r["id"]),
        )
        closed.append(r)
    return closed


def list_bills_for_entity(conn: sqlite3.Connection, entity_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM bills WHERE entity_id = ? ORDER BY bill_date DESC", (entity_id,)
    ).fetchall()


def list_bills_due(conn: sqlite3.Connection, entity_type: str) -> list[sqlite3.Row]:
    """Flat due-list for the Payable/Receivable views: every open/overdue bill for
    entities of the given type, joined with who it belongs to, soonest-due first.
    Bills with no known due date sort last, not first - an unknown due date isn't
    "due now"."""
    return conn.execute(
        """
        SELECT b.*, e.tally_ledger_name AS entity_name, e.id AS entity_id
        FROM bills b
        JOIN entities e ON e.id = b.entity_id
        WHERE e.entity_type = ? AND b.status IN ('open', 'overdue')
        ORDER BY (b.due_date IS NULL), b.due_date ASC
        """,
        (entity_type,),
    ).fetchall()


def count_open_overdue_bills(conn: sqlite3.Connection, entity_id: int) -> tuple[int, int]:
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count,
            SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) AS overdue_count
        FROM bills WHERE entity_id = ?
        """,
        (entity_id,),
    ).fetchone()
    return (row["open_count"] or 0, row["overdue_count"] or 0)


# ---------------------------------------------------------------------------
# Stock items
# ---------------------------------------------------------------------------

def upsert_stock_item(
    conn: sqlite3.Connection, item_name: str, qty: float, unit: Optional[str], value: float,
    seen_at: Optional[str] = None,
) -> sqlite3.Row:
    seen_at = seen_at or now_iso()
    normalized = normalize(item_name)
    row = conn.execute(
        """
        INSERT INTO stock_items (item_name, normalized_item_name, qty, unit, value, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(normalized_item_name) DO UPDATE SET
            item_name = excluded.item_name,
            qty = excluded.qty,
            unit = excluded.unit,
            value = excluded.value,
            last_seen_at = excluded.last_seen_at
        RETURNING *
        """,
        (item_name, normalized, qty, unit, value, seen_at),
    ).fetchone()
    return row


def list_stock_items(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM stock_items ORDER BY item_name").fetchall()


# ---------------------------------------------------------------------------
# Snapshots / balances / changes
# ---------------------------------------------------------------------------

def create_snapshot(
    conn: sqlite3.Connection, tally_reachable: bool, notes: Optional[str] = None, taken_at: Optional[str] = None
) -> sqlite3.Row:
    row = conn.execute(
        "INSERT INTO snapshots (taken_at, tally_reachable, notes) VALUES (?, ?, ?) RETURNING *",
        (taken_at or now_iso(), tally_reachable, notes),
    ).fetchone()
    return row


def get_previous_snapshot(conn: sqlite3.Connection, before_snapshot_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM snapshots WHERE id < ? ORDER BY id DESC LIMIT 1", (before_snapshot_id,)
    ).fetchone()


def write_snapshot_entity_balance(
    conn: sqlite3.Connection, snapshot_id: int, entity_id: int, balance: float, balance_type: Optional[str]
) -> None:
    conn.execute(
        """
        INSERT INTO snapshot_entity_balances (snapshot_id, entity_id, balance, balance_type)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(snapshot_id, entity_id) DO UPDATE SET
            balance = excluded.balance, balance_type = excluded.balance_type
        """,
        (snapshot_id, entity_id, balance, balance_type),
    )


def get_snapshot_entity_balance(conn: sqlite3.Connection, snapshot_id: int, entity_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM snapshot_entity_balances WHERE snapshot_id = ? AND entity_id = ?",
        (snapshot_id, entity_id),
    ).fetchone()


def write_change(
    conn: sqlite3.Connection,
    snapshot_id: int,
    change_type: str,
    message: str,
    entity_id: Optional[int] = None,
    stock_item_id: Optional[int] = None,
    old_value: Optional[float] = None,
    new_value: Optional[float] = None,
    delta: Optional[float] = None,
) -> sqlite3.Row:
    row = conn.execute(
        """
        INSERT INTO changes (
            snapshot_id, entity_id, stock_item_id, change_type,
            old_value, new_value, delta, message, detected_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        (snapshot_id, entity_id, stock_item_id, change_type, old_value, new_value, delta, message, now_iso()),
    ).fetchone()
    return row


def list_changes(conn: sqlite3.Connection, since: Optional[str] = None, limit: int = 50) -> list[sqlite3.Row]:
    if since:
        return conn.execute(
            "SELECT * FROM changes WHERE detected_at > ? ORDER BY detected_at DESC LIMIT ?",
            (since, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM changes ORDER BY detected_at DESC LIMIT ?", (limit,)
    ).fetchall()


# ---------------------------------------------------------------------------
# Followups - sync NEVER writes here. See 01_ARCHITECTURE_AND_DATA_MODEL.md.
# ---------------------------------------------------------------------------

def add_followup(conn: sqlite3.Connection, entity_id: int, note: str, status: str = "pending") -> sqlite3.Row:
    ts = now_iso()
    row = conn.execute(
        """
        INSERT INTO followups (entity_id, note, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?) RETURNING *
        """,
        (entity_id, note, status, ts, ts),
    ).fetchone()
    return row


def list_followups(conn: sqlite3.Connection, entity_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM followups WHERE entity_id = ? ORDER BY created_at DESC", (entity_id,)
    ).fetchall()


# ---------------------------------------------------------------------------
# Sync errors
# ---------------------------------------------------------------------------

def log_sync_error(conn: sqlite3.Connection, context: str, raw_record: str, reason: str) -> None:
    conn.execute(
        "INSERT INTO sync_errors (occurred_at, context, raw_record, reason) VALUES (?, ?, ?, ?)",
        (now_iso(), context, raw_record, reason),
    )


# ---------------------------------------------------------------------------
# Bank reconciliation
# ---------------------------------------------------------------------------

def create_bank_statement(conn: sqlite3.Connection, filename: str, row_count: int) -> sqlite3.Row:
    return conn.execute(
        "INSERT INTO bank_statements (filename, uploaded_at, row_count) VALUES (?, ?, ?) RETURNING *",
        (filename, now_iso(), row_count),
    ).fetchone()


def add_bank_transaction(
    conn: sqlite3.Connection, statement_id: int, txn_date: Optional[str], narration: str,
    reference: Optional[str], amount: float, direction: str,
    matched_entity_id: Optional[int] = None, matched_bill_ref: Optional[str] = None,
    match_confidence: Optional[float] = None, match_status: str = "unmatched",
) -> sqlite3.Row:
    return conn.execute(
        """
        INSERT INTO bank_transactions (
            statement_id, txn_date, narration, reference, amount, direction,
            matched_entity_id, matched_bill_ref, match_confidence, match_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *
        """,
        (statement_id, txn_date, narration, reference, amount, direction,
         matched_entity_id, matched_bill_ref, match_confidence, match_status),
    ).fetchone()


def list_bank_transactions(conn: sqlite3.Connection, statement_id: Optional[int] = None) -> list[sqlite3.Row]:
    if statement_id is not None:
        return conn.execute(
            """
            SELECT bt.*, e.tally_ledger_name AS matched_entity_name
            FROM bank_transactions bt
            LEFT JOIN entities e ON e.id = bt.matched_entity_id
            WHERE bt.statement_id = ?
            ORDER BY bt.txn_date ASC, bt.id ASC
            """,
            (statement_id,),
        ).fetchall()
    return conn.execute(
        """
        SELECT bt.*, e.tally_ledger_name AS matched_entity_name
        FROM bank_transactions bt
        LEFT JOIN entities e ON e.id = bt.matched_entity_id
        ORDER BY bt.txn_date DESC, bt.id DESC
        """
    ).fetchall()


def get_bank_transaction(conn: sqlite3.Connection, transaction_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone()


def set_bank_transaction_match(
    conn: sqlite3.Connection, transaction_id: int,
    matched_entity_id: Optional[int], matched_bill_ref: Optional[str],
    match_status: str, match_confidence: Optional[float] = None,
) -> sqlite3.Row:
    return conn.execute(
        """
        UPDATE bank_transactions
        SET matched_entity_id = ?, matched_bill_ref = ?, match_status = ?,
            match_confidence = COALESCE(?, match_confidence), confirmed_at = ?
        WHERE id = ? RETURNING *
        """,
        (matched_entity_id, matched_bill_ref, match_status, match_confidence, now_iso(), transaction_id),
    ).fetchone()
