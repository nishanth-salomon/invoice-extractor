"""Append-only JSONL audit log: what was read, what was decided, and why."""
import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, decision):
        inv = decision.invoice
        row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "file": decision.file, "sha256": decision.sha256,
               "method": decision.method, "status": decision.status.value,
               "vendor": inv.vendor, "invoice_number": inv.invoice_number, "total": str(inv.total) if inv.total is not None else None,
               "issues": [{"code": i.code, "field": i.field, "severity": i.severity, "message": i.message} for i in decision.issues]}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
