from datetime import date
from decimal import Decimal

from invoiceflow.config import Config
from invoiceflow.validate import VendorMemory, normalise, validate

TODAY = date(2026, 11, 6)
TEXT = "Acme Web Services Ltd\nInvoice No. INV-1\nDate: 12 Oct 2026\nTotal $108.00\nIBAN: GB29NWBK60161331926819"


def raw(**over):
    r = {"vendor": "Acme Web Services Ltd", "invoice_number": "INV-1", "invoice_date": "12 Oct 2026", "due_date": "11 Nov 2026",
         "currency": "USD", "subtotal": "100.00", "tax": "8.00", "discount": None, "total": "$108.00", "bank_account": "GB29NWBK60161331926819",
         "lines": [{"description": "x", "qty": "2", "unit_price": "50.00", "amount": "100.00"}], "confidence": {}, "doc_text": TEXT}
    r.update(over)
    return r


def mem():
    m = VendorMemory()
    m.remember("Acme Web Services Ltd", "GB29NWBK60161331926819")
    return m


def codes(r, memory=None, cfg=None):
    inv = normalise(r)
    return {i.code for i in validate(inv, r, cfg or Config(), memory or mem(), TODAY) if i.severity == "block"}


def test_clean_invoice_has_no_blocking_issue():
    assert codes(raw()) == set()


def test_fabricated_invoice_number_is_caught_by_grounding():
    assert "UNGROUNDED_FIELD" in codes(raw(invoice_number="INV-7731"))


def test_digit_swapped_total_is_caught_by_arithmetic_and_grounding():
    c = codes(raw(total="$108.90"))
    assert "TOTAL_MISMATCH" in c and "UNGROUNDED_FIELD" in c


def test_total_recomputed_with_discount():
    r = raw(subtotal="100.00", discount="10.00", tax="7.20", total="97.20", doc_text=TEXT + "\n97.20")
    assert "TOTAL_MISMATCH" not in codes(r)


def test_dropped_row_breaks_subtotal():
    r = raw(subtotal="150.00", total="$158.00", doc_text=TEXT + "\n150.00\n158.00")
    assert "SUBTOTAL_MISMATCH" in codes(r)


def test_line_math_error():
    r = raw(lines=[{"description": "x", "qty": "2", "unit_price": "50.00", "amount": "90.00"}])
    assert "LINE_MATH" in codes(r)


def test_missing_critical_field():
    assert "MISSING_FIELD" in codes(raw(invoice_number=None))


def test_ambiguous_date_never_guessed():
    r = raw(invoice_date="03/04/2026", due_date="03/05/2026", doc_text=TEXT + "\n03/04/2026")
    assert "AMBIGUOUS_DATE" in codes(r)


def test_due_before_invoice_date_and_future_date():
    assert "DUE_BEFORE_DATE" in codes(raw(due_date="01 Oct 2026"))
    assert "FUTURE_DATE" in codes(raw(invoice_date="20 Dec 2026", doc_text=TEXT + "\n20 Dec 2026"))


def test_bank_change_flagged_for_known_vendor():
    r = raw(bank_account="US11NEWBANK00998877", doc_text=TEXT + "\nUS11NEWBANK00998877")
    assert "BANK_CHANGED" in codes(r)


def test_new_vendor_blocks_by_default_and_can_be_relaxed():
    r = raw(vendor="Totally New Co", doc_text=TEXT + "\nTotally New Co")
    assert "NEW_VENDOR" in codes(r)
    cfg = Config(review_new_vendors=False)
    assert "NEW_VENDOR" not in codes(r, cfg=cfg)


def test_round_amount_blocks_unknown_vendor_only():
    r = raw(vendor="Zed Ltd", subtotal="4237.29", tax="762.71", total="5000.00", lines=[], doc_text="Zed Ltd\nInvoice No. INV-1\n12 Oct 2026\n5000.00\nGB29NWBK60161331926819")
    assert "ROUND_AMOUNT" in codes(r)


def test_no_text_layer_without_second_reading_is_not_trusted():
    assert "NO_VERIFICATION" in codes(raw(doc_text=""))


def test_consensus_agreement_allows_image_only_input():
    alt = {k: v for k, v in raw().items() if k not in ("doc_text",)}
    assert "NO_VERIFICATION" not in codes(raw(doc_text="", alt=alt))
    assert "CONSENSUS_MISMATCH" not in codes(raw(doc_text="", alt=alt))


def test_consensus_disagreement_is_flagged():
    alt = raw(total="$180.00", subtotal="100.00")
    assert "CONSENSUS_MISMATCH" in codes(raw(doc_text="", alt=alt))


def test_low_model_confidence_on_critical_field_blocks():
    assert "LOW_CONFIDENCE" in codes(raw(confidence={"total": 0.5}))
    assert "LOW_CONFIDENCE" not in codes(raw(confidence={"total": 0.97}))


def test_unknown_currency_is_flagged():
    assert "UNKNOWN_CURRENCY" in codes(raw(currency="XYZ"))


def test_ambiguous_amount_is_flagged():
    r = raw(subtotal="1.234", total="1.234", tax=None, lines=[], doc_text=TEXT + "\n1.234")
    assert "AMBIGUOUS_AMOUNT" in codes(r)


def test_scans_always_review_policy_overrides_agreeing_readings():
    alt = {k: v for k, v in raw().items() if k != "doc_text"}
    assert "SCAN_POLICY" not in codes(raw(doc_text="", alt=alt))
    assert "SCAN_POLICY" in codes(raw(doc_text="", alt=alt), cfg=Config(scans_always_review=True))
