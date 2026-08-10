"""
Phase 1 verification script. No Tally needed - pure DB test.
Run: python test_db.py
"""
import os
import sqlite3

import db

TEST_DB_PATH = "test_phase1.db"


def fresh_db() -> sqlite3.Connection:
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    conn = db.connect(TEST_DB_PATH)
    db.init_db(conn)
    return conn


def check(label: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        raise SystemExit(1)


def main() -> None:
    conn = fresh_db()

    # 1. UNIQUE constraints exist at DB level
    tables_sql = {
        row["name"]: row["sql"]
        for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    }
    check("entities has UNIQUE on normalized_ledger_name", "normalized_ledger_name TEXT NOT NULL UNIQUE" in tables_sql["entities"])
    check("bills has UNIQUE(entity_id, bill_ref)", "UNIQUE(entity_id, bill_ref)" in tables_sql["bills"])
    check("stock_items has UNIQUE on normalized_item_name", "normalized_item_name TEXT NOT NULL UNIQUE" in tables_sql["stock_items"])

    # 2. Upsert same logical entity twice -> update, not duplicate
    e1 = db.upsert_entity(conn, "  ABC Traders ", "customer", 1000.0, "Dr")
    e2 = db.upsert_entity(conn, "ABC Traders", "customer", 1500.0, "Dr")  # different whitespace, same normalized key
    conn.commit()
    check("second upsert returns same entity id", e1["id"] == e2["id"])
    count = conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"]
    check("only one entities row exists after 2 upserts", count == 1)
    check("balance updated on second upsert", e2["current_balance"] == 1500.0)

    # last_changed_at should now be set (balance changed from insert default -> 1500)
    check("last_changed_at set after a real balance change", e2["last_changed_at"] is not None)

    # 3. Upsert with NO change -> last_changed_at must NOT move
    e3 = db.upsert_entity(conn, "ABC Traders", "customer", 1500.0, "Dr")
    conn.commit()
    check("last_changed_at unchanged when balance unchanged", e3["last_changed_at"] == e2["last_changed_at"])

    # 4. Bills upsert twice -> no duplicate
    b1 = db.upsert_bill(conn, e1["id"], "INV-001", "2026-01-01", "2026-02-01", 5000.0, 5000.0, "open", "high")
    b2 = db.upsert_bill(conn, e1["id"], "INV-001", "2026-01-01", "2026-02-01", 5000.0, 3000.0, "open", "high")
    conn.commit()
    check("second bill upsert returns same bill id", b1["id"] == b2["id"])
    bill_count = conn.execute("SELECT COUNT(*) c FROM bills").fetchone()["c"]
    check("only one bills row exists after 2 upserts", bill_count == 1)

    # 5. Stock item upsert twice -> no duplicate
    s1 = db.upsert_stock_item(conn, "Widget A", 100, "pcs", 10000.0)
    s2 = db.upsert_stock_item(conn, "Widget A", 90, "pcs", 9000.0)
    conn.commit()
    check("second stock upsert returns same id", s1["id"] == s2["id"])
    stock_count = conn.execute("SELECT COUNT(*) c FROM stock_items").fetchone()["c"]
    check("only one stock_items row exists after 2 upserts", stock_count == 1)

    # 6. sync_errors writable
    db.log_sync_error(conn, context="bill_match", raw_record='{"foo": "bar"}', reason="test")
    conn.commit()
    err_count = conn.execute("SELECT COUNT(*) c FROM sync_errors").fetchone()["c"]
    check("sync_errors table writable", err_count == 1)

    # 7. followups independent of sync tables, never touched by upsert paths
    db.add_followup(conn, e1["id"], "Called, promised payment by Friday")
    conn.commit()
    fu_count = conn.execute("SELECT COUNT(*) c FROM followups").fetchone()["c"]
    check("followups table writable", fu_count == 1)

    conn.close()
    os.remove(TEST_DB_PATH)
    print("\nAll Phase 1 checks passed.")


if __name__ == "__main__":
    main()
