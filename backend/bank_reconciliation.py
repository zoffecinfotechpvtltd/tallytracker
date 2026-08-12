"""
Bank statement reconciliation - matches bank transactions against open Tally
bills. This is the ONLY file that knows real-world bank statement export
quirks (column naming varies wildly by bank) and owns the fuzzy-matching
heuristic, same "one file owns the messy format" pattern as tally_client.py.

Nothing here ever writes to Tally or changes bill status - reconciliation
results are purely local tracking (bank_transactions table), confirmed by
the user, never auto-applied without review below the high-confidence bar.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Optional

import openpyxl
from rapidfuzz import fuzz

# Column header aliases seen across common bank statement exports. Matching is
# case-insensitive substring match against these candidates, in priority order.
_DATE_HEADERS = ["value date", "txn date", "transaction date", "date"]
_NARRATION_HEADERS = ["narration", "description", "particulars", "transaction remarks", "remarks"]
_DEBIT_HEADERS = ["debit", "withdrawal amt", "withdrawal amount", "dr amount", "debit amount"]
_CREDIT_HEADERS = ["credit", "deposit amt", "deposit amount", "cr amount", "credit amount"]
_REFERENCE_HEADERS = ["chq/ref no", "cheque no", "reference no", "ref no", "utr", "transaction id"]

# Common bank narration noise stripped before fuzzy-matching against ledger
# names, e.g. "NEFT-ABC TRADERS-UTR1234567890" -> "ABC TRADERS"
_NARRATION_NOISE_PATTERNS = [
    r"\b(NEFT|IMPS|RTGS|UPI|CHQ|CLG|ACH|ECS)\b",
    r"\bUTR\S*",
    r"\b\d{6,}\b",  # long numeric reference/UTR strings
]


class BankStatementError(Exception):
    """Raised when the uploaded file can't be parsed - unreadable format,
    no recognizable header row, or no data rows."""


def _match_col(headers: list[str], candidates: list[str]) -> Optional[int]:
    for candidate in candidates:
        for i, h in enumerate(headers):
            if h and candidate in h:
                return i
    return None


def _find_header_row(rows: list[tuple]) -> tuple[int, dict[str, Optional[int]]]:
    """Scans the first ~15 rows for one that looks like a header (matches
    enough of our known column aliases), returns (row_index, {field: col_index})."""
    for row_idx, row in enumerate(rows[:15]):
        headers = [str(c).strip().lower() if c is not None else "" for c in row]
        date_col = _match_col(headers, _DATE_HEADERS)
        narration_col = _match_col(headers, _NARRATION_HEADERS)
        debit_col = _match_col(headers, _DEBIT_HEADERS)
        credit_col = _match_col(headers, _CREDIT_HEADERS)
        if date_col is not None and narration_col is not None and (debit_col is not None or credit_col is not None):
            reference_col = _match_col(headers, _REFERENCE_HEADERS)
            return row_idx, {
                "date": date_col, "narration": narration_col,
                "debit": debit_col, "credit": credit_col, "reference": reference_col,
            }
    raise BankStatementError(
        "Could not find a header row with recognizable Date/Narration/Debit-Credit columns. "
        "Supported column names include: Date/Value Date/Txn Date, Narration/Description/Particulars, "
        "Debit/Withdrawal Amt, Credit/Deposit Amt."
    )


def _parse_amount(raw) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    cleaned = str(raw).replace(",", "").strip()
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _parse_date(raw) -> Optional[date]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    raw = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_bank_statement(file_bytes: bytes) -> list[dict]:
    """Parses an uploaded .xlsx bank statement into a flat transaction list:
    [{ "date": date|None, "narration": str, "reference": str|None,
       "amount": float, "direction": "credit"|"debit" }, ...]
    Column layout varies by bank - detected from the header row rather than
    assumed fixed positions."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    except Exception as e:
        raise BankStatementError(f"Could not read file as .xlsx: {e}") from e

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise BankStatementError("File has no rows.")

    header_idx, cols = _find_header_row(rows)

    results: list[dict] = []
    for row in rows[header_idx + 1:]:
        if row is None or all(c is None for c in row):
            continue
        narration = row[cols["narration"]] if cols["narration"] < len(row) else None
        if not narration or not str(narration).strip():
            continue
        debit_col, credit_col = cols["debit"], cols["credit"]
        debit = _parse_amount(row[debit_col]) if debit_col is not None and debit_col < len(row) else 0.0
        credit = _parse_amount(row[credit_col]) if credit_col is not None and credit_col < len(row) else 0.0
        if credit > 0:
            amount, direction = credit, "credit"
        elif debit > 0:
            amount, direction = debit, "debit"
        else:
            continue  # zero-amount row (opening balance line, section header, etc.) - skip

        reference = None
        ref_col = cols["reference"]
        if ref_col is not None and ref_col < len(row):
            ref_val = row[ref_col]
            reference = str(ref_val).strip() if ref_val is not None else None

        results.append({
            "date": _parse_date(row[cols["date"]]) if cols["date"] < len(row) else None,
            "narration": str(narration).strip(),
            "reference": reference,
            "amount": amount,
            "direction": direction,
        })

    if not results:
        raise BankStatementError("No transaction rows found under the detected header.")
    return results


def _clean_narration(narration: str) -> str:
    cleaned = narration.upper()
    for pattern in _NARRATION_NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def match_transaction(
    narration: str, amount: float, txn_date: Optional[date], candidate_bills: list[dict],
) -> Optional[dict]:
    """Scores every candidate bill against one bank transaction, returns the
    single best match (or None if nothing clears the floor).

    candidate_bills: [{ "entity_id": int, "entity_name": str, "bill_ref": str,
    "amount_outstanding": float, "due_date": date|None }, ...] - same-direction
    bills only (caller filters receivable vs payable before calling this).

    Amount weighs heaviest since it's the most reliable signal - bank
    narrations are frequently truncated/coded and can't be trusted alone.
    Returned "confidence" is 0-100:
      >= 85  -> strong match, safe to auto-suggest (still requires user
                confirmation before it's treated as reconciled - this never
                touches Tally or bill status either way)
      40-84  -> possible match, surfaced for manual review
      < 40   -> not returned at all, caller shows "no match found\""""
    cleaned_narration = _clean_narration(narration)
    best: Optional[dict] = None
    for bill in candidate_bills:
        outstanding = bill["amount_outstanding"]
        amount_pct_diff = abs(amount - outstanding) / outstanding if outstanding > 0 else 1.0
        if amount_pct_diff <= 0.001:
            amount_score = 100.0
        elif amount_pct_diff <= 0.02:
            amount_score = 80.0
        elif amount_pct_diff <= 0.05:
            amount_score = 50.0
        else:
            amount_score = 0.0

        name_score = fuzz.token_set_ratio(cleaned_narration, bill["entity_name"].upper())

        date_score = 50.0  # neutral when either date is unknown - don't punish missing data
        due_date = bill.get("due_date")
        if txn_date is not None and due_date is not None:
            days_diff = abs((txn_date - due_date).days)
            if days_diff <= 7:
                date_score = 100.0
            elif days_diff <= 30:
                date_score = 70.0
            elif days_diff <= 60:
                date_score = 40.0
            else:
                date_score = 10.0

        confidence = 0.5 * amount_score + 0.4 * name_score + 0.1 * date_score
        if best is None or confidence > best["confidence"]:
            best = {
                "entity_id": bill["entity_id"], "entity_name": bill["entity_name"],
                "bill_ref": bill["bill_ref"], "confidence": round(confidence, 1),
            }
    if best is not None and best["confidence"] >= 40:
        return best
    return None
