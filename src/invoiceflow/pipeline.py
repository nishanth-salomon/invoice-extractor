import hashlib
from datetime import date
from pathlib import Path

from .audit import AuditLog
from .config import Config
from .ledger import Ledger
from .models import Decision, Status
from .validate import VendorMemory, normalise, validate


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Pipeline:
    """extract -> normalise -> validate -> duplicate check -> route -> audit. Only the gates can approve."""

    def __init__(self, extractor, cfg=None, ledger=None, memory=None, audit=None, today=None):
        self.extractor, self.cfg = extractor, cfg or Config()
        self.ledger, self.memory, self.audit = ledger or Ledger(), memory or VendorMemory(), audit
        self.today = today or date.today()

    def process(self, path) -> Decision:
        path = Path(path)
        sha = sha256_of(path)
        try:
            raw = self.extractor.extract(path)
        except Exception as exc:  # an unreadable file is a review item, never a crash or a silent skip
            from .models import Invoice, Issue
            d = Decision(path.name, Status.REVIEW, Invoice(), [Issue("EXTRACTION_FAILED", "document", "block", f"{type(exc).__name__}: {exc}")], "failed", sha)
            if self.audit:
                self.audit.record(d)
            return d
        inv = normalise(raw)
        issues = validate(inv, raw, self.cfg, self.memory, self.today)
        exact, dup_issues = self.ledger.check(inv, sha, self.cfg)
        issues += dup_issues
        if exact:
            status = Status.DUPLICATE
        elif any(i.severity == "block" for i in issues):
            status = Status.REVIEW
        else:
            status = Status.APPROVED
        d = Decision(path.name, status, inv, issues, raw.get("method", ""), sha)
        if status is not Status.DUPLICATE:
            self.ledger.record(inv, sha, path.name, status.value)
        if status is Status.APPROVED:
            self.memory.remember(inv.vendor, inv.bank_account)
        if self.audit:
            self.audit.record(d)
        return d

    def process_folder(self, folder):
        files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg"))
        return [self.process(p) for p in files]
