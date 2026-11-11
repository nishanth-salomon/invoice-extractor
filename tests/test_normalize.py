from datetime import date
from decimal import Decimal

import pytest
from invoiceflow.normalize import (detect_currency, edit_distance, norm_number, normalize_vendor, parse_amount, parse_date)


@pytest.mark.parametrize("s,val,amb", [
    ("$1,234.56", "1234.56", False), ("1.234,56", "1234.56", False), ("€ 1 234,56", "1234.56", False),
    ("1,234,567.89", "1234567.89", False), ("(12.50)", "-12.50", False), ("-$99.00", "-99.00", False),
    ("1,234", "1234", False), ("1.234", "1.234", True), ("12,5", "12.5", False), ("INR 8,200.00", "8200.00", False)])
def test_parse_amount(s, val, amb):
    v, a = parse_amount(s)
    assert v == Decimal(val) and a is amb


def test_parse_amount_junk():
    assert parse_amount("n/a") == (None, False)
    assert parse_amount(None) == (None, False)


@pytest.mark.parametrize("s,d,amb", [
    ("2026-03-12", date(2026, 3, 12), False), ("12 Mar 2026", date(2026, 3, 12), False), ("March 12, 2026", date(2026, 3, 12), False),
    ("12.03.2026", date(2026, 3, 12), False), ("13/04/2026", date(2026, 4, 13), False), ("04/13/2026", date(2026, 4, 13), False),
    ("05/05/2026", date(2026, 5, 5), False), ("03/04/2026", date(2026, 3, 4), True)])
def test_parse_date(s, d, amb):
    assert parse_date(s) == (d, amb)


def test_parse_date_invalid():
    assert parse_date("31/02/2026") == (None, False)
    assert parse_date("") == (None, False)


def test_vendor_normalisation_matches_variants():
    assert normalize_vendor("Acme Ltd.") == normalize_vendor("ACME Limited") == "acme"
    assert normalize_vendor("Cedar & Pine Design Ltd") == "cedar pine design"


def test_number_and_edit_distance():
    assert norm_number("inv-2026/0412") == "INV20260412"
    assert edit_distance("INV20260412", "INV20260413") == 1
    assert edit_distance("abc", "abc") == 0 and edit_distance("", "abc") == 3


def test_currency_detection():
    assert detect_currency("£45.00") == "GBP" and detect_currency("Total EUR 10") == "EUR" and detect_currency("none") is None
