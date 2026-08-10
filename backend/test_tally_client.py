"""
Phase 2 verification script - run against your REAL, open Tally instance.

    python test_tally_client.py

Do not proceed to Phase 3 (poller/diff_engine) until this runs clean
against your actual Tally data. If a fetch function returns empty/wrong
data, re-run with debug dumping on to see Tally's actual raw XML:

    set TALLY_CLIENT_DEBUG=1        (PowerShell: $env:TALLY_CLIENT_DEBUG="1")
    python test_tally_client.py

then adjust tag names in tally_client.py only.
"""
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import tally_client as tc


def pretty_print(label: str, rows: list[dict]) -> None:
    print(f"\n=== {label} ({len(rows)} rows) ===")
    if not rows:
        print("  (no rows returned)")
        return
    for row in rows[:20]:
        print(f"  {row}")
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more")


def warn_missing_natural_keys(label: str, rows: list[dict], key: str) -> None:
    missing = [r for r in rows if not r.get(key)]
    if missing:
        print(f"WARNING: {len(missing)}/{len(rows)} rows in {label} missing natural key '{key}'")
        for m in missing[:5]:
            print(f"    {m}")


def main() -> int:
    print(f"Testing against Tally at {tc.TALLY_URL}\n")

    print("1) check_tally_alive() while Tally should be open ...")
    alive = tc.check_tally_alive()
    print(f"   -> {alive}")
    if not alive:
        print("Tally is not reachable. Open Tally with a company loaded and enable the")
        print("HTTP-XML server (Gateway of Tally > F1 Help > Settings > Connectivity),")
        print("then re-run this script.")
        return 1

    try:
        tb = tc.fetch_trial_balance()
        pretty_print("Trial Balance", tb)
        warn_missing_natural_keys("Trial Balance", tb, "ledger_name")

        br = tc.fetch_bills_receivable()
        pretty_print("Bills Receivable", br)
        warn_missing_natural_keys("Bills Receivable", br, "bill_ref")

        bp = tc.fetch_bills_payable()
        pretty_print("Bills Payable", bp)
        warn_missing_natural_keys("Bills Payable", bp, "bill_ref")

        stock = tc.fetch_stock_summary()
        pretty_print("Stock Summary", stock)
        warn_missing_natural_keys("Stock Summary", stock, "item_name")
    except tc.TallyUnreachableError as e:
        print(f"TallyUnreachableError during fetch: {e}")
        return 1

    print("\n2) Re-running trial balance fetch to confirm natural keys are stable across calls ...")
    tb2 = tc.fetch_trial_balance()
    names1 = [r["ledger_name"] for r in tb]
    names2 = [r["ledger_name"] for r in tb2]
    if names1 == names2:
        print("   PASS: identical ledger_name list/order/casing across two calls")
    else:
        print("   FAIL: ledger_name values differ between calls - investigate before Phase 3")
        print(f"   first call:  {names1}")
        print(f"   second call: {names2}")
        return 1

    print("\n3) Confirming check_tally_alive() goes False once Tally is closed ...")
    print("   Close Tally now. Waiting up to 30s ...")
    deadline = time.time() + 30
    went_false = False
    while time.time() < deadline:
        if not tc.check_tally_alive(timeout_s=tc.check_tally_alive.__defaults__[0]):
            went_false = True
            break
        time.sleep(2)
    if went_false:
        print("   PASS: check_tally_alive() returned False after Tally closed")
    else:
        print("   SKIPPED/FAIL: still returning True after 30s - close Tally and re-run "
              "this script (or run it interactively) to confirm this behavior manually")

    print("\nAll Phase 2 checks that could run automatically have completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
