"""
Throwaway diagnostic - not part of the app. Dumps the raw BILLALLOCATIONS.LIST
Tally returns for one specific ledger, so we can see exactly which bills
Tally's ad-hoc export includes/excludes without guessing.

Run (from backend/):  python tools/debug_ledger_bills.py "D A TECHNOLOGIES"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xml.etree.ElementTree as ET

import tally_client as tc

LEDGER_NAME = sys.argv[1] if len(sys.argv) > 1 else "D A TECHNOLOGIES"

for group_name in (tc.PAYABLE_GROUP, tc.RECEIVABLE_GROUP):
    print(f"\n{'=' * 70}\nGroup: {group_name}\n{'=' * 70}")
    req = tc._adhoc_collection_request(
        "TTBillsDebug",
        "Ledger",
        [
            "NAME", "PARENT",
            "BILLALLOCATIONS.NAME",
            "BILLALLOCATIONS.BILLTYPE",
            "BILLALLOCATIONS.BILLCREDITPERIOD",
            "BILLALLOCATIONS.OPENINGBALANCE",
            "BILLALLOCATIONS.CLOSINGBALANCE",
        ],
        filter_expr=f'$Parent = "{group_name}"',
    )
    raw = tc._post(req)
    root = tc._parse_xml(raw)

    found = False
    for led in root.iter("LEDGER"):
        name = tc._object_name(led)
        if not name or tc._normalize_name(name) != tc._normalize_name(LEDGER_NAME):
            continue
        found = True
        parent = led.get("PARENT") or led.findtext("PARENT") or ""
        print(f"Ledger matched: {name!r} (parent={parent!r})")
        bill_lists = led.findall("BILLALLOCATIONS.LIST")
        print(f"BILLALLOCATIONS.LIST count: {len(bill_lists)}")
        for i, bill in enumerate(bill_lists):
            print(f"\n--- bill #{i} raw XML ---")
            print(ET.tostring(bill, encoding="unicode"))
    if not found:
        print(f"No ledger named {LEDGER_NAME!r} found under this group's export.")

print(f"\n\nTotal raw response length for last group: {len(raw)} chars")
