"""Duplicate detection against everything processed before: exact match and one-digit-changed near duplicates."""
import json
from datetime import timedelta
from pathlib import Path

from .models import Issue
from .normalize import edit_distance, norm_number, normalize_vendor


class Ledger:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.rows = []
        if self.path and self.path.exists():
            self.rows = [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def check(self, inv, sha, cfg):
        """Return (is_exact_duplicate, issues)."""
        v, n = normalize_vendor(inv.vendor), norm_number(inv.invoice_number)
        for r in self.rows:
            if r["sha256"] == sha:
                return True, [Issue("DUPLICATE_FILE", "file", "block", f"identical file already processed as {r['file']}")]
            if r["vendor"] == v and n and r["number"] == n:
                return True, [Issue("DUPLICATE_INVOICE", "invoice_number", "block", f"vendor + invoice number already processed ({r['file']})")]
        issues = []
        for r in self.rows:
            if r["vendor"] != v or not v:
                continue
            same_total = inv.total is not None and r["total"] == str(inv.total)
            close_number = n and r["number"] and 0 < edit_distance(n, r["number"]) <= 1
            close_date = (inv.invoice_date is not None and r["date"] and
                          abs((inv.invoice_date - type(inv.invoice_date).fromisoformat(r["date"])).days) <= cfg.dup_window_days)
            if same_total and (close_number or close_date):
                issues.append(Issue("NEAR_DUPLICATE", "invoice_number", "block",
                                    f"same vendor and amount as {r['file']} with a near-identical number/date"))
                break
        return False, issues

    def record(self, inv, sha, file, status):
        row = {"file": file, "sha256": sha, "vendor": normalize_vendor(inv.vendor), "number": norm_number(inv.invoice_number),
               "total": str(inv.total) if inv.total is not None else None,
               "date": inv.invoice_date.isoformat() if inv.invoice_date else None, "status": status}
        self.rows.append(row)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
