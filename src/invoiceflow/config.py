import json
from dataclasses import dataclass, field, fields
from decimal import Decimal
from pathlib import Path


@dataclass
class Config:
    """Business rules live here, not in code. Override any key from a JSON file."""
    tolerance_abs: Decimal = Decimal("0.02")
    tolerance_rel: Decimal = Decimal("0.001")
    critical_fields: tuple = ("vendor", "invoice_number", "invoice_date", "total", "currency")
    # a model's self-reported confidence is only a routing hint, never proof
    min_confidence: dict = field(default_factory=lambda: {
        "total": 0.90, "invoice_number": 0.90, "vendor": 0.80, "invoice_date": 0.85, "bank_account": 0.95, "default": 0.70})
    review_new_vendors: bool = True
    round_amount_multiple: int = 100
    round_amount_min: int = 1000
    max_invoice_age_days: int = 730
    future_days: int = 3
    dup_window_days: int = 3
    require_consensus_without_text: bool = True
    scans_always_review: bool = False  # True: image-only documents never auto-approve, even when two readings agree


def load_config(path=None) -> Config:
    cfg = Config()
    if path and Path(path).exists():
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        names = {f.name for f in fields(Config)}
        for k, v in data.items():
            if k in names:
                if k in ("tolerance_abs", "tolerance_rel"):
                    v = Decimal(str(v))
                elif k == "critical_fields":
                    v = tuple(v)
                setattr(cfg, k, v)
    return cfg
