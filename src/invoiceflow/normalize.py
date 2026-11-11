"""Locale-safe parsing. Ambiguity is reported, never silently guessed."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
KNOWN_CURRENCIES = {"USD", "EUR", "GBP", "INR", "CAD", "AUD"}
_VENDOR_SUFFIXES = {"inc", "llc", "ltd", "limited", "gmbh", "pvt", "corp", "corporation", "co", "company", "pty", "plc", "sa", "bv", "ag"}


def detect_currency(text):
    if not text:
        return None
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in text:
            return code
    m = re.search(r"\b(USD|EUR|GBP|INR|CAD|AUD)\b", text.upper())
    return m.group(1) if m else None


def parse_amount(s):
    """Return (Decimal | None, ambiguous). Handles 1,234.56 / 1.234,56 / 1 234,56 / (12.00) / -12.00."""
    if s is None:
        return None, False
    raw = str(s).strip()
    neg = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")")) or raw.upper().endswith("CR")
    t = re.sub(r"[^\d.,]", "", raw.replace(" ", "").replace(" ", ""))
    if not re.search(r"\d", t):
        return None, False
    amb = False
    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        thou = "." if dec == "," else ","
        t = t.replace(thou, "").replace(dec, ".")
    elif "," in t or "." in t:
        sep = "," if "," in t else "."
        parts = t.split(sep)
        if len(parts) > 2:
            t = "".join(parts)
        elif len(parts[1]) == 3:
            if sep == ",":
                t = "".join(parts)          # 1,234 -> thousands
            else:
                amb = True                  # 1.234 -> decimal in English, thousands in many locales
        else:
            t = parts[0] + "." + parts[1]
    try:
        val = Decimal(t)
    except InvalidOperation:
        return None, False
    return (-val if neg else val), amb


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d.%m.%Y")
_NUMERIC = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$")


def parse_date(s):
    """Return (date | None, ambiguous). 03/04/2026 is ambiguous and flagged; 13/04/2026 is not."""
    if not s:
        return None, False
    t = re.sub(r"\s+", " ", str(s).strip().rstrip("."))
    m = _NUMERIC.match(t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            if a > 12:
                return date(y, b, a), False
            if b > 12:
                return date(y, a, b), False
            return date(y, a, b), a != b
        except ValueError:
            return None, False
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date(), False
        except ValueError:
            continue
    return None, False


def normalize_vendor(name):
    if not name:
        return ""
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    while words and words[-1] in _VENDOR_SUFFIXES:
        words.pop()
    return " ".join(words)


def norm_number(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def edit_distance(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
