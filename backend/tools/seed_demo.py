"""
DEMO DATA ONLY - for looking at the UI before real Tally is connected.
Populates backend/tally.db with fake entities/bills/stock, deliberately
including two different customers that both use invoice ref "INV-001" -
proves entity segregation (same ref, different party, no collision).

Run (from backend/):  python tools/seed_demo.py
Clear afterwards: stop the server, delete backend/tally.db, restart
(a fresh empty DB is recreated automatically).
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tally.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

import db
import poller
import tally_client
from datetime import date

conn = db.connect(DB_PATH)
db.init_db(conn)

FAKE_TB = [
    {"ledger_name": "ABC Traders", "balance": 15000.0, "balance_type": "Dr"},
    {"ledger_name": "Global Imports Ltd", "balance": 220500.5, "balance_type": "Dr"},
    {"ledger_name": "Sunrise Hardware", "balance": 3200.0, "balance_type": "Dr"},
    {"ledger_name": "Nirmal Enterprises", "balance": 67250.0, "balance_type": "Dr"},
    {"ledger_name": "Metro Steel Co", "balance": 48000.0, "balance_type": "Cr"},
    {"ledger_name": "Prime Packaging", "balance": 9800.0, "balance_type": "Cr"},
    {"ledger_name": "Kaveri Logistics", "balance": 15600.0, "balance_type": "Cr"},
]
# Note: ABC Traders and Nirmal Enterprises both use ref "INV-001" -
# proves bills stay scoped per entity, never mixed.
FAKE_BILLS_R = [
    {"ledger_name": "ABC Traders", "bill_ref": "INV-001", "bill_date": date(2026, 6, 1), "due_date": date(2026, 7, 1),
     "original_amount": 15000.0, "amount_outstanding": 15000.0},
    {"ledger_name": "Nirmal Enterprises", "bill_ref": "INV-001", "bill_date": date(2026, 7, 20), "due_date": date(2026, 8, 20),
     "original_amount": 40000.0, "amount_outstanding": 40000.0},
    {"ledger_name": "Nirmal Enterprises", "bill_ref": "INV-014", "bill_date": date(2026, 6, 15), "due_date": date(2026, 7, 15),
     "original_amount": 27250.0, "amount_outstanding": 27250.0},
    {"ledger_name": "Global Imports Ltd", "bill_ref": "INV-2026-014", "bill_date": date(2026, 5, 10), "due_date": date(2026, 6, 10),
     "original_amount": 220500.5, "amount_outstanding": 220500.5},
    {"ledger_name": "Sunrise Hardware", "bill_ref": "INV-2026-020", "bill_date": date(2026, 7, 15), "due_date": date(2026, 8, 20),
     "original_amount": 3200.0, "amount_outstanding": 3200.0},
]
FAKE_BILLS_P = [
    {"ledger_name": "Metro Steel Co", "bill_ref": "PB-889", "bill_date": date(2026, 6, 20), "due_date": date(2026, 7, 20),
     "original_amount": 48000.0, "amount_outstanding": 48000.0},
    {"ledger_name": "Prime Packaging", "bill_ref": "PB-902", "bill_date": date(2026, 7, 1), "due_date": date(2026, 8, 5),
     "original_amount": 9800.0, "amount_outstanding": 9800.0},
    {"ledger_name": "Kaveri Logistics", "bill_ref": "PB-915", "bill_date": date(2026, 5, 28), "due_date": date(2026, 6, 28),
     "original_amount": 15600.0, "amount_outstanding": 15600.0},
]
FAKE_STOCK = [
    {"item_name": "Steel Rod 12mm", "qty": 450.0, "unit": "pcs", "value": 225000.0},
    {"item_name": "Cement Bag 50kg", "qty": 8.0, "unit": "bag", "value": 3200.0},
    {"item_name": "Packaging Tape", "qty": 5.0, "unit": "roll", "value": 750.0},
    {"item_name": "Corrugated Box L", "qty": 320.0, "unit": "pcs", "value": 48000.0},
    {"item_name": "PVC Pipe 2in", "qty": 4.0, "unit": "pcs", "value": 2400.0},
]

tally_client.check_tally_alive = lambda timeout_s=2.5: True
tally_client.fetch_trial_balance = lambda: list(FAKE_TB)
tally_client.fetch_bills_receivable = lambda: list(FAKE_BILLS_R)
tally_client.fetch_bills_payable = lambda: list(FAKE_BILLS_P)
tally_client.fetch_stock_summary = lambda: list(FAKE_STOCK)

r1 = poller.run_sync_cycle(conn)
print("initial sync:", r1)

# a second cycle with one real change, so the Margin Notes feed has
# something realistic in it too (not just "new" onboarding rows)
FAKE_TB[0] = {"ledger_name": "ABC Traders", "balance": 18500.0, "balance_type": "Dr"}
FAKE_BILLS_R[4]["amount_outstanding"] = 0.0
r2 = poller.run_sync_cycle(conn)
print("second sync (1 balance change + 1 bill settled):", r2)

print(f"\nentities: {conn.execute('SELECT COUNT(*) c FROM entities').fetchone()['c']}")
print(f"bills: {conn.execute('SELECT COUNT(*) c FROM bills').fetchone()['c']}")
conn.close()
print("\nDemo data ready. Start the server and open http://127.0.0.1:8731/")
