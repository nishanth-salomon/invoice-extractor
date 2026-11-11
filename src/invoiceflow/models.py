from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class Status(str, Enum):
    APPROVED = "approved"
    REVIEW = "needs_review"
    DUPLICATE = "duplicate"


@dataclass
class Issue:
    code: str
    field: str
    severity: str  # "block" routes to review; "warn" is recorded but does not block
    message: str


@dataclass
class LineItem:
    description: str
    qty: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None


@dataclass
class Invoice:
    vendor: str = ""
    invoice_number: str = ""
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    discount: Decimal | None = None
    total: Decimal | None = None
    bank_account: str | None = None
    lines: list[LineItem] = field(default_factory=list)
    date_ambiguous: bool = False
    amount_ambiguous: bool = False


@dataclass
class Decision:
    file: str
    status: Status
    invoice: Invoice
    issues: list[Issue]
    method: str = ""
    sha256: str = ""
