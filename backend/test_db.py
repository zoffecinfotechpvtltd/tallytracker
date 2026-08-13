"""
Phase 1 tests - pure DB layer, no Tally needed.
Run: pytest test_db.py  (or just `pytest` from backend/)
"""
import os
import sqlite3

import pytest

import db


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    c = db.connect(str(tmp_path / "test_phase1.db"))
    db.init_db(c)
    yield c
    c.close()


def _table_sql(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["name"]: row["sql"]
        for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    }


def test_entities_has_unique_normalized_name(conn):
    assert "normalized_ledger_name TEXT NOT NULL UNIQUE" in _table_sql(conn)["entities"]


def test_bills_has_unique_entity_and_ref(conn):
    assert "UNIQUE(entity_id, bill_ref)" in _table_sql(conn)["bills"]


def test_stock_items_has_unique_normalized_name(conn):
    assert "normalized_item_name TEXT NOT NULL UNIQUE" in _table_sql(conn)["stock_items"]


def test_entity_upsert_dedupes_on_normalized_name(conn):
    e1 = db.upsert_entity(conn, "  ABC Traders ", "customer", 1000.0, "Dr")
    e2 = db.upsert_entity(conn, "ABC Traders", "customer", 1500.0, "Dr")  # different whitespace, same key
    conn.commit()

    assert e1["id"] == e2["id"]
    count = conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]
    assert count == 1
    assert e2["current_balance"] == 1500.0
    assert e2["last_changed_at"] is not None  # real balance change must stamp it


def test_entity_upsert_noop_does_not_move_last_changed_at(conn):
    e1 = db.upsert_entity(conn, "ABC Traders", "customer", 1000.0, "Dr")
    e2 = db.upsert_entity(conn, "ABC Traders", "customer", 1500.0, "Dr")
    conn.commit()
    e3 = db.upsert_entity(conn, "ABC Traders", "customer", 1500.0, "Dr")  # no change this time
    conn.commit()
    assert e3["last_changed_at"] == e2["last_changed_at"]


def test_bill_upsert_dedupes_on_entity_and_ref(conn):
    e1 = db.upsert_entity(conn, "ABC Traders", "customer", 1000.0, "Dr")
    b1 = db.upsert_bill(conn, e1["id"], "INV-001", "2026-01-01", "2026-02-01", 5000.0, 5000.0, "open", "high")
    b2 = db.upsert_bill(conn, e1["id"], "INV-001", "2026-01-01", "2026-02-01", 5000.0, 3000.0, "open", "high")
    conn.commit()

    assert b1["id"] == b2["id"]
    bill_count = conn.execute("SELECT COUNT(*) c FROM bills").fetchone()["c"]
    assert bill_count == 1


def test_bill_narration_stored_and_updated(conn):
    e1 = db.upsert_entity(conn, "ABC Traders", "customer", 1000.0, "Dr")
    b1 = db.upsert_bill(
        conn, e1["id"], "INV-001", "2026-01-01", "2026-02-01", 5000.0, 5000.0, "open", "high",
        narration="Sale of 10 units Widget A",
    )
    assert b1["narration"] == "Sale of 10 units Widget A"

    b2 = db.upsert_bill(
        conn, e1["id"], "INV-001", "2026-01-01", "2026-02-01", 5000.0, 3000.0, "open", "high",
        narration="Sale of 10 units Widget A (revised)",
    )
    assert b2["narration"] == "Sale of 10 units Widget A (revised)"


def test_stock_item_upsert_dedupes_on_normalized_name(conn):
    s1 = db.upsert_stock_item(conn, "Widget A", 100, "pcs", 10000.0)
    s2 = db.upsert_stock_item(conn, "Widget A", 90, "pcs", 9000.0)
    conn.commit()

    assert s1["id"] == s2["id"]
    stock_count = conn.execute("SELECT COUNT(*) c FROM stock_items").fetchone()["c"]
    assert stock_count == 1


def test_sync_errors_table_writable(conn):
    db.log_sync_error(conn, context="bill_match", raw_record='{"foo": "bar"}', reason="test")
    conn.commit()
    err_count = conn.execute("SELECT COUNT(*) c FROM sync_errors").fetchone()["c"]
    assert err_count == 1


def test_init_db_is_idempotent_and_versioned(conn):
    # conn fixture already ran init_db once via db.init_db(c); running it
    # again (e.g. every process start) must not error or re-apply migrations.
    db.init_db(conn)
    version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
    assert version == len(db._MIGRATIONS)


def test_backup_database_copies_file_and_prunes_old_ones(tmp_path):
    db_path = tmp_path / "tally.db"
    db_path.write_bytes(b"fake db contents")
    backup_dir = tmp_path / "backups"

    import time
    paths = []
    for _ in range(3):
        p = db.backup_database(str(db_path), str(backup_dir), keep=2, label="test")
        assert p is not None
        paths.append(p)
        time.sleep(1.01)  # filenames are second-resolution timestamps; force distinct names

    remaining = sorted(os.listdir(backup_dir))
    assert len(remaining) == 2  # pruned down to `keep`
    assert os.path.basename(paths[-1]) in remaining  # most recent survives


def test_backup_database_noop_when_source_missing(tmp_path):
    assert db.backup_database(str(tmp_path / "missing.db"), str(tmp_path / "backups")) is None


def test_maybe_daily_backup_is_a_noop_second_call_same_day(tmp_path):
    db_path = tmp_path / "tally.db"
    c = db.connect(str(db_path))
    db.init_db(c)

    first = db.maybe_daily_backup(c)
    assert first is not None
    second = db.maybe_daily_backup(c)
    assert second is None  # already backed up today
    c.close()


def test_followups_independent_of_sync_tables(conn):
    e1 = db.upsert_entity(conn, "ABC Traders", "customer", 1000.0, "Dr")
    db.add_followup(conn, e1["id"], "Called, promised payment by Friday")
    conn.commit()
    fu_count = conn.execute("SELECT COUNT(*) c FROM followups").fetchone()["c"]
    assert fu_count == 1
