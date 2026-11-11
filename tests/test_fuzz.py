"""Corrupt one digit/char of what the extractor returns and check nothing wrong is ever approved.
This is the property the tool exists for: a wrong value must route to review, not to the books."""
import re
from datetime import date
from pathlib import Path

import pytest
from invoiceflow.config import Config
from invoiceflow.extractors import TextLayerExtractor
from invoiceflow.ledger import Ledger
from invoiceflow.models import Status
from invoiceflow.pipeline import Pipeline
from invoiceflow.validate import VendorMemory

CORPUS = Path(__file__).resolve().parents[1] / "samples" / "corpus"
CLEAN = ["01_acme_clean.pdf", "02_nordlicht_eu.pdf", "03_bluepeak_multipage.pdf", "04_harbor_discount.pdf", "05_cedar_vat.pdf"]
SEED = [("Acme Web Services Ltd", "GB29NWBK60161331926819"), ("Nordlicht Software GmbH", "DE89370400440532013000"),
        ("BluePeak Industrial Supply Inc", "US64SVBKUS6S3300958879"), ("Harbor Logistics Pvt Ltd", "IN2200123456789"),
        ("Cedar & Pine Design Ltd", "GB82WEST12345698765432")]


class Corrupting:
    def __init__(self, field, nth=0):
        self.inner, self.field, self.nth = TextLayerExtractor(), field, nth

    def extract(self, path):
        raw = self.inner.extract(path)
        v = raw[self.field]
        digits = [m.start() for m in re.finditer(r"\d", v)]
        i = digits[min(self.nth, len(digits) - 1)]
        raw[self.field] = v[:i] + str((int(v[i]) + 1) % 10) + v[i + 1:]
        return raw


def run(name, extractor):
    mem = VendorMemory()
    for v, b in SEED:
        mem.remember(v, b)
    return Pipeline(extractor, Config(), Ledger(), mem, None, today=date(2026, 11, 6)).process(CORPUS / name)


@pytest.mark.parametrize("name", CLEAN)
def test_uncorrupted_baseline_is_approved(name):
    assert run(name, TextLayerExtractor()).status is Status.APPROVED


@pytest.mark.parametrize("field", ["total", "subtotal", "invoice_number", "invoice_date", "bank_account"])
@pytest.mark.parametrize("nth", [0, 2])
@pytest.mark.parametrize("name", CLEAN)
def test_single_digit_corruption_is_never_approved(name, field, nth):
    d = run(name, Corrupting(field, nth))
    assert d.status is not Status.APPROVED, f"{name}: corrupted {field} (digit #{nth}) was approved"
