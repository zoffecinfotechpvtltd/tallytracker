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
import threading
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Optional
from xml.sax.saxutils import escape as _xml_escape

from config import settings

TALLY_HOST = os.environ.get("TALLY_HOST", "localhost")
TALLY_PORT = int(os.environ.get("TALLY_PORT", "9000"))
TALLY_URL = f"http://{TALLY_HOST}:{TALLY_PORT}"

_DEFAULT_COMPANY_PLACEHOLDER = "Your Company Name"


def _current_company_tag() -> str:
    """Pin requests to the company set in config.yaml, so results don't silently
    depend on whichever company happens to be active in the Tally UI. Skipped
    when left at the placeholder default (single-company setups still work
    off whatever's open)."""
    name = (settings.tally.company_name or "").strip()
    if not name or name == _DEFAULT_COMPANY_PLACEHOLDER:
        return ""
    return f"<SVCURRENTCOMPANY>{_xml_escape(name)}</SVCURRENTCOMPANY>"

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


_MIN_REQUEST_INTERVAL_S = 1.0
_request_lock = threading.Lock()
_last_request_at = 0.0


def _throttle() -> None:
    """Tally's single-client XML server appears unable to handle back-to-back
    requests with no gap - a sync cycle firing 5 requests in a tight loop
    (alive-check + 4 fetches) consistently came back empty across all of them,
    while isolated single requests spaced out in time worked fine. Enforcing a
    minimum gap between any two requests this process makes to Tally."""
    global _last_request_at
    with _request_lock:
        wait = _last_request_at + _MIN_REQUEST_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _post(xml_body: str, timeout_s: float = 10.0) -> str:
    _throttle()
    data = xml_body.encode("utf-8")
    req = urllib.request.Request(TALLY_URL, data=data, headers={"Content-Type": "text/xml"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise TallyUnreachableError(f"Could not reach Tally at {TALLY_URL}: {e}") from e
    _debug("raw response", raw)
    return raw


_XML_ILLEGAL_CODEPOINTS = {0xB, 0xC, 0xFFFE, 0xFFFF}


def _is_xml_illegal_codepoint(cp: int) -> bool:
    return (
        cp in _XML_ILLEGAL_CODEPOINTS
        or (0x0 <= cp <= 0x8) or (0xE <= cp <= 0x1F)
        or (0xD800 <= cp <= 0xDFFF)
    )


def _strip_illegal_numeric_refs(match: "re.Match[str]") -> str:
    cp = int(match.group(1), 16) if match.group(1) else int(match.group(2))
    return "" if _is_xml_illegal_codepoint(cp) else match.group(0)


def _parse_xml(raw: str) -> ET.Element:
    # Tally sometimes emits invalid XML control characters - as raw bytes AND as
    # escaped numeric character references (e.g. "&#4;") inside ledger/item names.
    # XML 1.0 forbids both forms for these codepoints; ET rejects the whole
    # document if even one slips through, so both must be scrubbed.
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
    cleaned = re.sub(r"&#x([0-9A-Fa-f]+);|&#(\d+);", _strip_illegal_numeric_refs, cleaned)
    cleaned = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)", "&amp;", cleaned)
    try:
        return ET.fromstring(cleaned)
    except ET.ParseError as e:
        raise TallyUnreachableError(f"Malformed XML from Tally: {e}") from e


def _text(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None or elem.text is None:
        return None
    t = elem.text.strip()
    return t if t else None


def _object_name(elem: ET.Element) -> Optional[str]:
    """Tally represents an object's own name two different ways depending on
    object type: as the NAME="..." attribute on the element itself (LEDGER,
    STOCKITEM), or as a child <NAME> element (COMPANY). elem.find("NAME") only
    ever sees the child-element form, so it silently returns None - and every
    caller here treats "no name" as "skip this record" - for LEDGER/STOCKITEM,
    which never emit the child form. Try the attribute first."""
    attr = elem.get("NAME")
    if attr and attr.strip():
        return attr.strip()
    return _text(elem.find("NAME"))


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


# Deliberately NOT bound to SVCURRENTCOMPANY - this must succeed as long as Tally
# itself is up, even if config.yaml's company_name is wrong/stale. Also doubles
# as the "what companies are actually open" probe - see fetch_company_list().
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


def fetch_company_list() -> list[str]:
    """Returns the exact company name strings Tally has open right now - copy one
    of these verbatim into config.yaml's tally.company_name (spacing/case/&
    must match exactly, this is a literal string match on Tally's side)."""
    raw = _post(_MINIMAL_PROBE)
    root = _parse_xml(raw)
    names: list[str] = []
    for company in root.iter("COMPANY"):
        name = _object_name(company)
        if name:
            names.append(name)
    return names


def _adhoc_collection_request(collection_name: str, obj_type: str, fetch_fields: list[str],
                               filter_expr: Optional[str] = None, extra_static_vars: str = "") -> str:
    fetch_tag = "\n     ".join(f"<FETCH>{f}</FETCH>" for f in fetch_fields)
    filter_block = ""
    system_filter = ""
    if filter_expr:
        filter_block = "<FILTER>TTFilterX2</FILTER>"
        system_filter = f"<SYSTEM TYPE=\"Formulae\" NAME=\"TTFilterX2\">{filter_expr}</SYSTEM>"
    return f"""<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>{collection_name}</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
    {_current_company_tag()}
    {extra_static_vars}
   </STATICVARIABLES>
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
        "TTLedgersX2", "Ledger", ["NAME", "PARENT", "CLOSINGBALANCE"],
    )
    raw = _post(req)
    root = _parse_xml(raw)

    results: list[dict] = []
    for led in root.iter("LEDGER"):
        name = _object_name(led)
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
        "TTBillsX2",
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
        ledger_name = _object_name(led)
        if not ledger_name:
            continue
        for bill in led.findall("BILLALLOCATIONS.LIST"):
            if len(bill) == 0:
                continue  # Tally emits an empty wrapper for ledgers with no open bills
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


_TALLY_JD_EPOCH = date(1899, 12, 30)  # UNVERIFIED against real data - see _julian_day_to_date()


def _julian_day_to_date(jd_raw: Optional[str]) -> Optional[date]:
    """Confirmed against real data: BILLCREDITPERIOD often carries TYPE="Due Date"
    with an EMPTY text value and the real due date encoded only in a JD="..."
    attribute (a serial day count), not in the element text at all - same shape
    of bug as ledger names living in an attribute instead of a child element.
    The epoch here (1899-12-30, the common Excel/Lotus spreadsheet-serial
    convention) is a best guess, NOT yet confirmed against this install: run
    test_tally_client.py, pick one bill whose due date you can see in Tally's
    own UI, and compare - adjust _TALLY_JD_EPOCH by the day count difference if
    it's off. Never used to silently produce a wrong date without this check."""
    try:
        return _TALLY_JD_EPOCH + timedelta(days=int(jd_raw))
    except (TypeError, ValueError, OverflowError):
        return None


def _extract_bill_dates(bill_elem: ET.Element) -> tuple[Optional[date], Optional[date]]:
    """BillAllocations doesn't always carry an explicit bill date; Tally derives it
    from the originating voucher, which raw ledger-collection export doesn't expose.
    BILLCREDITPERIOD can show up three ways depending on how the bill's credit
    terms were configured: a JD-attribute-encoded due date (see
    _julian_day_to_date), a plain integer in the text (days of credit, add to
    bill_date), or an explicit date string in the text - handle all three."""
    bill_date = _parse_tally_date(_first_text(bill_elem, "BILLDATE"))
    credit_elem = bill_elem.find("BILLCREDITPERIOD")
    due_date: Optional[date] = None
    if credit_elem is not None:
        jd_raw = credit_elem.get("JD")
        if credit_elem.get("TYPE") == "Due Date" and jd_raw:
            due_date = _julian_day_to_date(jd_raw)
        else:
            credit_raw = _text(credit_elem)
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
        "TTStockX2", "StockItem",
        ["NAME", "BASEUNITS", "CLOSINGBALANCE", "CLOSINGVALUE"],
    )
    raw = _post(req)
    root = _parse_xml(raw)

    results: list[dict] = []
    for item in root.iter("STOCKITEM"):
        name = _object_name(item)
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


def _normalize_name(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).casefold()


def fetch_vouchers_for_ledger(ledger_name: str, limit: int = 100, lookback_days: int = 365) -> list[dict]:
    """Returns recent transactions where the given ledger appears in the voucher,
    newest first: [{ "date": date|None, "voucher_type": str, "voucher_number": str,
    "amount": float, "narration": str }, ...].

    Confirmed against real Tally data, three separate bugs:
    1. AMOUNT is NOT a top-level Voucher field - only exposed per leg, inside
       each ALLLEDGERENTRIES.LIST entry. Fixed by reading the amount from
       whichever entry's LEDGERNAME matches the ledger being viewed.
    2. $PartyLedgerName filtering (which worked for a Payment voucher) came back
       completely empty for a salary ledger with a real, non-zero balance -
       "party" is an invoice-style concept (Payment/Receipt/Sales/Purchase) that
       Journal vouchers (how things like salary provisioning post) don't have,
       so that filter silently excludes entire voucher types. Replaced with a
       date-range scope (no party filter at all) plus the client-side
       ledger-entry match already used for the amount, which catches every
       voucher type since it just inspects the real line items.
    3. Whether Tally includes ALLLEDGERENTRIES.LIST at all depends on the
       query shape, not a fixed rule: a request matching one specific voucher
       returned the full native object (every native sub-list) regardless of
       the requested FETCH fields, but a broad date-range scan matching many
       vouchers returned a lean summary form with ALLLEDGERENTRIES.LIST
       omitted entirely - same as the ad-hoc dotted-path trick already used in
       _fetch_bills() (BILLALLOCATIONS.NAME etc.), explicitly FETCHing
       ALLLEDGERENTRIES.LEDGERNAME / ALLLEDGERENTRIES.AMOUNT forces Tally to
       include that sub-list even in the broad scan."""
    from_date = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    to_date = date.today().strftime("%Y%m%d")
    date_range_vars = f'<SVFROMDATE TYPE="Date">{from_date}</SVFROMDATE><SVTODATE TYPE="Date">{to_date}</SVTODATE>'
    req = _adhoc_collection_request(
        "TTVouchersX2", "Voucher",
        [
            "DATE", "VOUCHERTYPENAME", "VOUCHERNUMBER", "NARRATION",
            "ALLLEDGERENTRIES.LEDGERNAME", "ALLLEDGERENTRIES.AMOUNT",
        ],
        extra_static_vars=date_range_vars,
    )

    # Same intermittent-empty-result fault as everywhere else this Tally
    # install talks to us (see poller._fetch_all) - a whole year of company-
    # wide vouchers coming back with zero <VOUCHER> elements is implausible,
    # so treat that as a signal to retry rather than a true "no data" result.
    root = None
    for attempt in range(1, 4):
        raw = _post(req)
        root = _parse_xml(raw)
        if any(True for _ in root.iter("VOUCHER")) or attempt == 3:
            break
        time.sleep(2.0)

    target = _normalize_name(ledger_name)

    results: list[dict] = []
    for v in root.iter("VOUCHER"):
        amount = None
        for entry in v.findall("ALLLEDGERENTRIES.LIST"):
            entry_ledger = _first_text(entry, "LEDGERNAME")
            if entry_ledger and _normalize_name(entry_ledger) == target:
                amount = _parse_amount(_first_text(entry, "AMOUNT"))
                break
        if amount is None:
            continue  # this ledger's own leg wasn't in this voucher - skip rather than show a wrong amount
        results.append({
            "date": _parse_tally_date(_first_text(v, "DATE")),
            "voucher_type": _first_text(v, "VOUCHERTYPENAME") or "",
            "voucher_number": _first_text(v, "VOUCHERNUMBER") or "",
            "amount": abs(amount),
            "narration": _first_text(v, "NARRATION") or "",
        })
    results.sort(key=lambda r: r["date"] or date.min, reverse=True)
    return results[:limit]


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
