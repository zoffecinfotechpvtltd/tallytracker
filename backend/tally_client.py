"""
Phase 2 - Tally XML Client.

This is the ONLY file in the whole project allowed to know Tally's XML tag
names. Every other module calls the functions below and gets back plain
Python dicts/lists. If your Tally version's tags differ from what's assumed
here, THIS is the only file you should ever need to edit.

No `tally_tracker.py` reference script was found in this project, so the
request bodies below were written from scratch using Tally's standard
ad-hoc "Collection" XML export pattern (define a throwaway TDL COLLECTION
inline in the request body, naming exactly the native object fields you
want back). This pattern is version-tolerant by design because it does not
depend on any of Tally's built-in report layouts, which change more
between ERP 9 / TallyPrime releases than the underlying object schema does.

TAGS MOST LIKELY TO NEED ADJUSTMENT FOR YOUR TALLY VERSION/DATA
(run test_tally_client.py against your real Tally first; if a field comes
back empty/wrong, set env var TALLY_CLIENT_DEBUG=1 and re-run to dump the
raw XML Tally actually returned, then fix the relevant spot below):
  - RECEIVABLE_GROUP / PAYABLE_GROUP constants below - must match your
    Tally chart of accounts group names (default Tally names assumed).
  - CLOSINGBALANCE sign convention for balance_type (Dr/Cr) - Tally's
    convention can appear inverted depending on report vs. raw object
    export; see _balance_type_from_signed_value().
  - Bill due date: raw BillAllocations objects don't always expose an
    explicit due-date field the same way across versions - see
    _extract_bill_dates() and its candidate tag list.
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Optional

TALLY_HOST = os.environ.get("TALLY_HOST", "localhost")
TALLY_PORT = int(os.environ.get("TALLY_PORT", "9000"))
TALLY_URL = f"http://{TALLY_HOST}:{TALLY_PORT}"

DEBUG = os.environ.get("TALLY_CLIENT_DEBUG", "") == "1"

# Adjust these to match your Tally chart of accounts if you use custom group names.
RECEIVABLE_GROUP = "Sundry Debtors"
PAYABLE_GROUP = "Sundry Creditors"


class TallyUnreachableError(Exception):
    """Raised for any connection failure, timeout, or malformed XML from Tally.
    Callers only ever need to handle this one exception type."""


def _debug(label: str, raw: str) -> None:
    if DEBUG:
        print(f"\n--- TALLY_CLIENT_DEBUG: {label} ---", file=sys.stderr)
        print(raw, file=sys.stderr)
        print(f"--- end {label} ---\n", file=sys.stderr)


def _post(xml_body: str, timeout_s: float = 10.0) -> str:
    data = xml_body.encode("utf-8")
    req = urllib.request.Request(TALLY_URL, data=data, headers={"Content-Type": "text/xml"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise TallyUnreachableError(f"Could not reach Tally at {TALLY_URL}: {e}") from e
    _debug("raw response", raw)
    return raw


def _parse_xml(raw: str) -> ET.Element:
    # Tally sometimes emits invalid XML control characters and an unescaped '&' in names.
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
    cleaned = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;)", "&amp;", cleaned)
    try:
        return ET.fromstring(cleaned)
    except ET.ParseError as e:
        raise TallyUnreachableError(f"Malformed XML from Tally: {e}") from e


def _text(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None or elem.text is None:
        return None
    t = elem.text.strip()
    return t if t else None


def _first_text(parent: ET.Element, *tags: str) -> Optional[str]:
    for tag in tags:
        found = parent.find(tag)
        val = _text(found)
        if val is not None:
            return val
    return None


def _parse_amount(raw: Optional[str]) -> float:
    if not raw:
        return 0.0
    cleaned = raw.replace(",", "").strip()
    negative = cleaned.startswith("-")
    cleaned = cleaned.lstrip("-").strip()
    try:
        val = float(cleaned) if cleaned else 0.0
    except ValueError:
        val = 0.0
    return -val if negative else val


def _parse_tally_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    # Compact numeric form Tally commonly emits: YYYYMMDD
    if re.fullmatch(r"\d{8}", raw):
        try:
            return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
        except ValueError:
            return None
    # Human form Tally also emits depending on export settings: D-MMM-YYYY / D-MMM-YY
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d"):
        try:
            from datetime import datetime
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _balance_type_from_signed_value(signed_value: float) -> str:
    """Tally's raw object export convention: positive CLOSINGBALANCE = Debit,
    negative = Credit. If your data comes back with balances that look sign-
    inverted vs. what Tally's UI shows, flip this."""
    return "Dr" if signed_value >= 0 else "Cr"


def check_tally_alive(timeout_s: float = 2.5) -> bool:
    try:
        _post(_MINIMAL_PROBE, timeout_s=timeout_s)
        return True
    except TallyUnreachableError:
        return False


_MINIMAL_PROBE = """<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>List of Companies</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
   </STATICVARIABLES>
  </DESC>
 </BODY>
</ENVELOPE>"""


def _adhoc_collection_request(collection_name: str, obj_type: str, fetch_fields: list[str],
                               filter_expr: Optional[str] = None) -> str:
    fetch_tag = "\n     ".join(f"<FETCH>{f}</FETCH>" for f in fetch_fields)
    filter_block = ""
    system_filter = ""
    if filter_expr:
        filter_block = "<FILTER>TallyTrackerFilter</FILTER>"
        system_filter = f"<SYSTEM TYPE=\"Formulae\" NAME=\"TallyTrackerFilter\">{filter_expr}</SYSTEM>"
    return f"""<ENVELOPE>
 <HEADER>
  <TALLYREQUEST>Export Data</TALLYREQUEST>
 </HEADER>
 <BODY>
  <EXPORTDATA>
   <REQUESTDESC>
    <REPORTNAME>{collection_name}</REPORTNAME>
    <STATICVARIABLES>
     <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
    </STATICVARIABLES>
   </REQUESTDESC>
  </EXPORTDATA>
  <DESC>
   <TDL>
    <TDLMESSAGE>
     <COLLECTION NAME="{collection_name}" ISMODIFY="No">
      <TYPE>{obj_type}</TYPE>
      {filter_block}
      {fetch_tag}
     </COLLECTION>
     {system_filter}
    </TDLMESSAGE>
   </TDL>
  </DESC>
 </BODY>
</ENVELOPE>"""


def fetch_trial_balance() -> list[dict]:
    """Returns: [{ "ledger_name": str, "balance": float, "balance_type": "Dr"|"Cr" }, ...]"""
    req = _adhoc_collection_request(
        "TallyTrackerLedgers", "Ledger", ["NAME", "PARENT", "CLOSINGBALANCE"],
    )
    raw = _post(req)
    root = _parse_xml(raw)

    results: list[dict] = []
    for led in root.iter("LEDGER"):
        name = _text(led.find("NAME"))
        if not name:
            continue
        signed = _parse_amount(_text(led.find("CLOSINGBALANCE")))
        results.append({
            "ledger_name": name,
            "balance": abs(signed),
            "balance_type": _balance_type_from_signed_value(signed),
        })
    return results


def _fetch_bills(group_name: str) -> list[dict]:
    req = _adhoc_collection_request(
        "TallyTrackerBills",
        "Ledger",
        [
            "NAME", "PARENT",
            "BILLALLOCATIONS.NAME",
            "BILLALLOCATIONS.BILLTYPE",
            "BILLALLOCATIONS.BILLCREDITPERIOD",
            "BILLALLOCATIONS.OPENINGBALANCE",
            "BILLALLOCATIONS.CLOSINGBALANCE",
        ],
        filter_expr=f"$Parent = \"{group_name}\"",
    )
    raw = _post(req)
    root = _parse_xml(raw)

    results: list[dict] = []
    for led in root.iter("LEDGER"):
        ledger_name = _text(led.find("NAME"))
        if not ledger_name:
            continue
        for bill in led.findall("BILLALLOCATIONS.LIST"):
            bill_ref = _first_text(bill, "NAME")
            bill_date, due_date = _extract_bill_dates(bill)
            original = _parse_amount(_first_text(bill, "OPENINGBALANCE"))
            outstanding = _parse_amount(_first_text(bill, "CLOSINGBALANCE"))
            results.append({
                "ledger_name": ledger_name,
                "bill_ref": bill_ref,
                "bill_date": bill_date,
                "due_date": due_date,
                "original_amount": abs(original) if original else abs(outstanding),
                "amount_outstanding": abs(outstanding),
            })
    return results


def _extract_bill_dates(bill_elem: ET.Element) -> tuple[Optional[date], Optional[date]]:
    """BillAllocations doesn't always carry an explicit bill date; Tally derives it
    from the originating voucher, which raw ledger-collection export doesn't expose.
    BILLCREDITPERIOD's raw text is either a plain integer (days of credit) or an
    explicit date (when the bill was configured with a fixed due date) - handle both."""
    bill_date = _parse_tally_date(_first_text(bill_elem, "BILLDATE"))
    credit_raw = _first_text(bill_elem, "BILLCREDITPERIOD")
    due_date: Optional[date] = None
    if credit_raw:
        as_date = _parse_tally_date(credit_raw)
        if as_date is not None:
            due_date = as_date
        else:
            digits = re.search(r"\d+", credit_raw)
            if digits and bill_date is not None:
                due_date = bill_date + timedelta(days=int(digits.group()))
    return bill_date, due_date


def fetch_bills_receivable() -> list[dict]:
    """Same shape as documented in 02_TALLY_XML_CLIENT.md, sourced from RECEIVABLE_GROUP."""
    return _fetch_bills(RECEIVABLE_GROUP)


def fetch_bills_payable() -> list[dict]:
    """Same shape as fetch_bills_receivable(), for vendor-side bills."""
    return _fetch_bills(PAYABLE_GROUP)


def fetch_stock_summary() -> list[dict]:
    """Returns: [{ "item_name": str, "qty": float, "unit": str, "value": float }, ...]"""
    req = _adhoc_collection_request(
        "TallyTrackerStock", "StockItem",
        ["NAME", "BASEUNITS", "CLOSINGBALANCE", "CLOSINGVALUE"],
    )
    raw = _post(req)
    root = _parse_xml(raw)

    results: list[dict] = []
    for item in root.iter("STOCKITEM"):
        name = _text(item.find("NAME"))
        if not name:
            continue
        qty_raw = _text(item.find("CLOSINGBALANCE")) or ""
        qty, unit_from_qty = _split_qty_unit(qty_raw)
        unit = _text(item.find("BASEUNITS")) or unit_from_qty
        value = _parse_amount(_text(item.find("CLOSINGVALUE")))
        results.append({
            "item_name": name,
            "qty": qty,
            "unit": unit,
            "value": abs(value),
        })
    return results


def _split_qty_unit(raw: str) -> tuple[float, Optional[str]]:
    """Tally often emits stock qty as a combined string like '100 pcs' or '-5 Nos'."""
    if not raw:
        return 0.0, None
    match = re.match(r"\s*(-?[\d,]*\.?\d+)\s*([A-Za-z%]*)\s*", raw)
    if not match:
        return 0.0, None
    qty_str, unit_str = match.groups()
    qty = _parse_amount(qty_str)
    return qty, (unit_str or None)
