"""Deterministic gates. The extractor (LLM or rules) can only propose; these checks decide what is trusted."""
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from .models import Invoice, Issue, LineItem
from .normalize import (KNOWN_CURRENCIES, detect_currency, norm_number, normalize_vendor, parse_amount, parse_date)


def normalise(raw) -> Invoice:
    """Turn verbatim strings into typed values and remember any ambiguity."""
    inv = Invoice(vendor=(raw.get("vendor") or "").strip(), invoice_number=(raw.get("invoice_number") or "").strip())
    inv.invoice_date, a1 = parse_date(raw.get("invoice_date"))
    inv.due_date, a2 = parse_date(raw.get("due_date"))
    inv.date_ambiguous = a1 or a2
    amb = False
    for f in ("subtotal", "tax", "discount", "total"):
        val, a = parse_amount(raw.get(f))
        setattr(inv, f, val)
        amb = amb or a
    cur = (raw.get("currency") or "").strip().upper()
    if cur in KNOWN_CURRENCIES:
        inv.currency = cur
    elif cur:
        inv.currency = detect_currency(cur)  # a stated but unrecognised currency stays unknown and is flagged, not guessed
    else:
        inv.currency = detect_currency(raw.get("total"))
    inv.bank_account = re.sub(r"\s+", "", raw["bank_account"]).upper() if raw.get("bank_account") else None
    for ln in raw.get("lines") or []:
        qty, a3 = parse_amount(ln.get("qty"))
        unit, a4 = parse_amount(ln.get("unit_price"))
        amt, a5 = parse_amount(ln.get("amount"))
        amb = amb or a3 or a4 or a5
        inv.lines.append(LineItem((ln.get("description") or "").strip(), qty, unit, amt))
    inv.amount_ambiguous = amb
    return inv


class VendorMemory:
    """Remembers vendors and their bank details so a new vendor or a changed account is noticed."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.data = {}
        if self.path and self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def known(self, vendor):
        return normalize_vendor(vendor) in self.data

    def banks(self, vendor):
        return self.data.get(normalize_vendor(vendor), {}).get("banks", [])

    def remember(self, vendor, bank=None):
        rec = self.data.setdefault(normalize_vendor(vendor), {"banks": [], "invoices": 0})
        rec["invoices"] += 1
        if bank and bank not in rec["banks"]:
            rec["banks"].append(bank)
        self.save()

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")


def _tol(x, cfg):
    return max(cfg.tolerance_abs, abs(x) * cfg.tolerance_rel)


def _squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _amount_in_text(value, text):
    for tok in re.findall(r"[\d][\d.,\s]*\d|\d", text):
        v, _ = parse_amount(tok)
        if v is not None and v == value:
            return True
        v2, _ = parse_amount(tok.strip().replace(" ", ""))
        if v2 is not None and v2 == value:
            return True
    return False


def _grounded(field, raw_value, parsed, text):
    if raw_value is None or raw_value == "":
        return True
    if field in ("total", "subtotal", "tax", "discount"):
        return parsed is None or _amount_in_text(abs(parsed), text)
    return _squash(str(raw_value)) in _squash(text)


def validate(inv: Invoice, raw, cfg, memory: VendorMemory, today: date):
    issues = []
    add = lambda code, f, sev, msg: issues.append(Issue(code, f, sev, msg))
    # 1. required fields
    for f in cfg.critical_fields:
        v = getattr(inv, f)
        if v in (None, "", []):
            add("MISSING_FIELD", f, "block", f"{f} was not found on the invoice")
    # 2. ambiguity is flagged, never guessed
    if inv.date_ambiguous:
        add("AMBIGUOUS_DATE", "invoice_date", "block", "date could be day-first or month-first; confirm the format")
    if inv.amount_ambiguous:
        add("AMBIGUOUS_AMOUNT", "total", "block", "an amount like 1.234 could use a decimal point or a thousands separator; confirm")
    # 3. arithmetic, recomputed in code and never trusted from the model
    for i, ln in enumerate(inv.lines, 1):
        if ln.qty is not None and ln.unit_price is not None and ln.amount is not None:
            if abs(ln.qty * ln.unit_price - ln.amount) > _tol(ln.amount, cfg):
                add("LINE_MATH", f"lines[{i}]", "block", f"line {i}: {ln.qty} x {ln.unit_price} is not {ln.amount}")
    lines_sum = sum((ln.amount for ln in inv.lines if ln.amount is not None), Decimal(0)) if inv.lines else None
    if inv.subtotal is not None and lines_sum is not None and abs(lines_sum - inv.subtotal) > _tol(inv.subtotal, cfg):
        add("SUBTOTAL_MISMATCH", "subtotal", "block", f"line items sum to {lines_sum} but subtotal is {inv.subtotal}; a row may be missing or duplicated")
    base = inv.subtotal if inv.subtotal is not None else lines_sum
    if base is not None and inv.total is not None:
        expected = base - abs(inv.discount or Decimal(0)) + (inv.tax or Decimal(0))
        if abs(expected - inv.total) > _tol(inv.total, cfg):
            add("TOTAL_MISMATCH", "total", "block", f"expected {expected} (subtotal - discount + tax) but total is {inv.total}")
    elif inv.total is not None:
        add("UNVERIFIABLE_TOTAL", "total", "warn", "no subtotal or line items, so the total could not be recomputed")
    if not inv.lines:
        add("NO_LINE_ITEMS", "lines", "warn", "no line items were extracted")
    # 4. dates and currency
    if inv.invoice_date:
        if inv.invoice_date > today + timedelta(days=cfg.future_days):
            add("FUTURE_DATE", "invoice_date", "block", f"invoice date {inv.invoice_date} is in the future")
        if (today - inv.invoice_date).days > cfg.max_invoice_age_days:
            add("OLD_INVOICE", "invoice_date", "warn", f"invoice is older than {cfg.max_invoice_age_days} days")
        if inv.due_date and inv.due_date < inv.invoice_date:
            add("DUE_BEFORE_DATE", "due_date", "block", "due date is before the invoice date")
    if raw.get("currency") and inv.currency is None:
        add("UNKNOWN_CURRENCY", "currency", "block", f"currency '{raw.get('currency')}' is not recognised")
    # 5. grounding: values must exist in the document itself (catches fabricated identifiers)
    text = raw.get("doc_text") or ""
    alt = raw.get("alt")
    if text:
        for f in ("vendor", "invoice_number", "invoice_date", "total", "bank_account"):
            if not _grounded(f, raw.get(f), getattr(inv, f) if f == "total" else None, text):
                add("UNGROUNDED_FIELD", f, "block", f"'{raw.get(f)}' does not appear in the document text; the extractor may have invented it")
    elif alt is None and cfg.require_consensus_without_text:
        add("NO_VERIFICATION", "document", "block", "no text layer and no second independent reading to verify against")
    if not text and cfg.scans_always_review:
        add("SCAN_POLICY", "document", "block", "image-only document: policy requires a human to confirm (two readings from one model can share an error)")
    if alt is not None:
        a = normalise(alt)
        diffs = [f for f, same in (("vendor", normalize_vendor(a.vendor) == normalize_vendor(inv.vendor)),
                                   ("invoice_number", norm_number(a.invoice_number) == norm_number(inv.invoice_number)),
                                   ("invoice_date", a.invoice_date == inv.invoice_date),
                                   ("total", a.total == inv.total)) if not same]
        if diffs:
            add("CONSENSUS_MISMATCH", ",".join(diffs), "block", f"two independent readings disagree on: {', '.join(diffs)}")
    # 6. model self-reported confidence (routing hint only)
    for f, c in (raw.get("confidence") or {}).items():
        need = cfg.min_confidence.get(f, cfg.min_confidence["default"])
        if isinstance(c, (int, float)) and c < need and f in cfg.critical_fields + ("bank_account",):
            add("LOW_CONFIDENCE", f, "block", f"model confidence {c:.2f} is below {need:.2f}")
    # 7. risk flags
    if inv.vendor and not memory.known(inv.vendor):
        add("NEW_VENDOR", "vendor", "block" if cfg.review_new_vendors else "warn", "first invoice from this vendor")
    elif inv.vendor and inv.bank_account:
        banks = memory.banks(inv.vendor)
        if banks and inv.bank_account not in banks:
            add("BANK_CHANGED", "bank_account", "block", "bank details differ from the ones on file for this vendor (common fraud pattern)")
    if inv.total is not None and inv.total >= cfg.round_amount_min and inv.total % cfg.round_amount_multiple == 0:
        add("ROUND_AMOUNT", "total", "warn" if memory.known(inv.vendor) else "block", f"round total {inv.total}")
    return issues
