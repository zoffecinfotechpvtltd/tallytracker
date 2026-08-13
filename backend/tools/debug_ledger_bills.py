"""
Throwaway diagnostic - not part of the app. Shows what _fetch_bills() would
actually return for one ledger, split by source (ledger-master opening-
balance snapshot vs. voucher-scan), so we can see exactly which bills come
from where without guessing.

Run (from backend/):  python tools/debug_ledger_bills.py "D A TECHNOLOGIES"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tally_client as tc

LEDGER_NAME = sys.argv[1] if len(sys.argv) > 1 else "D A TECHNOLOGIES"
target = tc._normalize_name(LEDGER_NAME)

for group_name in (tc.PAYABLE_GROUP, tc.RECEIVABLE_GROUP):
    print(f"\n{'=' * 70}\nGroup: {group_name}\n{'=' * 70}")

    group_ledgers = tc._fetch_group_ledger_names(group_name)
    matches = [n for n in group_ledgers if tc._normalize_name(n) == target]
    if not matches:
        print(f"No ledger named {LEDGER_NAME!r} under this group.")
        continue
    print(f"Ledger found under this group: {matches[0]!r}")

    full = tc._fetch_bills(group_name)
    mine = [b for b in full if tc._normalize_name(b["ledger_name"]) == target]
    mine.sort(key=lambda b: b["bill_date"] or __import__("datetime").date.min)

    print(f"\n_fetch_bills() total rows for this ledger: {len(mine)}\n")
    for b in mine:
        print(
            f"  {b['bill_date']}  {b['bill_ref']:<20}  "
            f"due={b['due_date']}  amount={b['amount_outstanding']:>12,.2f}"
        )

    if mine:
        years = sorted({b["bill_date"].year for b in mine if b["bill_date"]})
        print(f"\nYears present: {years}")
