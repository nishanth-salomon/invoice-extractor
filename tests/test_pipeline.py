import csv
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from invoiceflow.audit import AuditLog
from invoiceflow.cli import main as cli_main
from invoiceflow.config import Config, load_config
from invoiceflow.export import PRESETS, rows_for, write_outputs
from invoiceflow.extractors import (ClaudeVisionExtractor, FallbackExtractor, TextLayerExtractor, _clean_vendor, pdf_lines)
from invoiceflow.ledger import Ledger
from invoiceflow.models import Status
from invoiceflow.pipeline import Pipeline
from invoiceflow.validate import VendorMemory

CORPUS = Path(__file__).resolve().parents[1] / "samples" / "corpus"
TODAY = date(2026, 11, 6)


def pipe(extractor=None, audit=None, seed=True):
    mem = VendorMemory()
    if seed:
        mem.remember("Acme Web Services Ltd", "GB29NWBK60161331926819")
    return Pipeline(extractor or TextLayerExtractor(), Config(), Ledger(), mem, audit, today=TODAY)


def test_clean_pdf_is_approved_with_correct_data():
    d = pipe().process(CORPUS / "01_acme_clean.pdf")
    assert d.status is Status.APPROVED and str(d.invoice.total) == "1100.52" and d.invoice.invoice_number == "INV-2026-0412"
    assert len(d.invoice.lines) == 5


def test_multipage_table_is_fully_read():
    p = pipe(seed=False)
    p.memory.remember("BluePeak Industrial Supply Inc", "US64SVBKUS6S3300958879")
    d = p.process(CORPUS / "03_bluepeak_multipage.pdf")
    assert len(pdf_lines(CORPUS / "03_bluepeak_multipage.pdf")) >= 2 and len(d.invoice.lines) == 60 and d.status is Status.APPROVED


def test_exact_duplicate_and_near_duplicate():
    p = pipe()
    assert p.process(CORPUS / "01_acme_clean.pdf").status is Status.APPROVED
    assert p.process(CORPUS / "09_acme_exact_duplicate.pdf").status is Status.DUPLICATE
    d = p.process(CORPUS / "10_acme_near_duplicate.pdf")
    assert d.status is Status.REVIEW and any(i.code == "NEAR_DUPLICATE" for i in d.issues)


def test_same_vendor_and_number_in_a_different_file_is_a_duplicate(tmp_path):
    p = pipe()
    p.process(CORPUS / "01_acme_clean.pdf")
    # a re-saved copy with different bytes but identical content fields
    from invoiceflow.models import Invoice
    inv = p.ledger.rows[0]
    exact, issues = p.ledger.check(SimpleNamespace(vendor="ACME Web Services Limited", invoice_number="inv 2026 0412", total=None, invoice_date=None), "different-hash", p.cfg)
    assert exact and issues[0].code == "DUPLICATE_INVOICE"


def test_scan_only_pdf_is_not_trusted():
    d = pipe().process(CORPUS / "13_harbor_scan_only.pdf")
    assert d.status is Status.REVIEW


def test_unreadable_file_goes_to_review_not_crash(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    d = pipe().process(bad)
    assert d.status is Status.REVIEW and d.issues[0].code == "EXTRACTION_FAILED"


def test_vendor_memory_is_updated_only_on_approval():
    p = pipe(seed=False)
    p.process(CORPUS / "12_zenith_round_new_vendor.pdf")
    assert not p.memory.known("Zenith Consulting LLC")


def test_clean_vendor_title_strip():
    assert _clean_vendor("Acme Ltd INVOICE") == "Acme Ltd" and _clean_vendor("Nordlicht GmbH Rechnung / Invoice") == "Nordlicht GmbH"


# ---- Claude adapter with a fake client: no network, no cost
class FakeClient:
    def __init__(self, *payloads, boom=False):
        self.payloads, self.calls, self.boom = list(payloads), [], boom
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise RuntimeError("api down")
        block = SimpleNamespace(type="tool_use", name="record_invoice", input=self.payloads.pop(0))
        return SimpleNamespace(content=[block])


class FakeOpenAIClient:
    """Mimics chat.completions.create with function calling; returns the payload as a JSON arguments string."""
    def __init__(self, *payloads, boom=False):
        self.payloads, self.calls, self.boom = list(payloads), [], boom
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise RuntimeError("api down")
        import json as _j
        fn = SimpleNamespace(name="record_invoice", arguments=_j.dumps(self.payloads.pop(0)))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[SimpleNamespace(function=fn)]))])


GOOD = {"vendor": "Acme Web Services Ltd", "invoice_number": "INV-2026-0412", "invoice_date": "12 Oct 2026", "total": "$1,100.52",
        "subtotal": "$1,019.00", "tax": "$81.52", "currency": "USD", "bank_account": "GB29NWBK60161331926819", "lines": [
            {"description": "Website maintenance (hours)", "qty": "6", "unit_price": "$85.00", "amount": "$510.00"},
            {"description": "Hosting, annual", "qty": "1", "unit_price": "$240.00", "amount": "$240.00"},
            {"description": "SSL certificate", "qty": "2", "unit_price": "$35.50", "amount": "$71.00"},
            {"description": "Support call-out", "qty": "3", "unit_price": "$60.00", "amount": "$180.00"},
            {"description": "Domain renewal", "qty": "1", "unit_price": "$18.00", "amount": "$18.00"}]}


def test_claude_extractor_forces_tool_and_marks_document_untrusted():
    client = FakeClient(dict(GOOD), dict(GOOD))
    raw = ClaudeVisionExtractor(client).extract(CORPUS / "01_acme_clean.pdf")
    call = client.calls[0]
    assert call["tool_choice"] == {"type": "auto"} and "exactly once" in call["system"] and "untrusted" in call["system"]
    assert call["messages"][0]["content"][0]["type"] == "image" and raw["method"] == "claude-vision" and "alt" in raw and raw["doc_text"]


def test_hallucinated_invoice_number_from_model_never_reaches_approved():
    bad = dict(GOOD, invoice_number="INV-9999-FAKE")
    d = pipe(ClaudeVisionExtractor(FakeClient(bad, dict(GOOD)))).process(CORPUS / "01_acme_clean.pdf")
    assert d.status is Status.REVIEW and {"UNGROUNDED_FIELD", "CONSENSUS_MISMATCH"} <= {i.code for i in d.issues}


def test_model_digit_error_in_total_never_reaches_approved():
    bad = dict(GOOD, total="$1,100.25")
    d = pipe(ClaudeVisionExtractor(FakeClient(bad, dict(GOOD)))).process(CORPUS / "01_acme_clean.pdf")
    assert d.status is Status.REVIEW


def test_model_output_matching_the_document_is_approved():
    d = pipe(ClaudeVisionExtractor(FakeClient(dict(GOOD), dict(GOOD)))).process(CORPUS / "01_acme_clean.pdf")
    assert d.status is Status.APPROVED


def test_fallback_to_rules_when_api_is_down_and_it_is_recorded():
    ex = FallbackExtractor(ClaudeVisionExtractor(FakeClient(boom=True)), TextLayerExtractor())
    d = pipe(ex).process(CORPUS / "01_acme_clean.pdf")
    assert d.status is Status.APPROVED and "fallback after RuntimeError" in d.method


# ---- exports, audit, config, CLI
def test_export_presets_use_plain_numbers_and_preset_dates():
    d = pipe().process(CORPUS / "01_acme_clean.pdf")
    g = rows_for(d.invoice, "generic")[0]
    x = rows_for(d.invoice, "xero")[0]
    q = rows_for(d.invoice, "quickbooks")[0]
    assert g[2] == "2026-10-12" and x[2] == "12/10/2026" and q[2] == "10/12/2026"
    assert "," not in "".join(g[5:8]) and g[7] == "1100.52"
    assert len(g) == len(PRESETS["generic"]["cols"]) and len(x) == len(PRESETS["xero"]["cols"]) and len(q) == len(PRESETS["quickbooks"]["cols"])


def test_audit_log_is_append_only_jsonl(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    p = pipe(audit=log)
    p.process(CORPUS / "01_acme_clean.pdf")
    p.process(CORPUS / "06_acme_math_error.pdf")
    rows = [json.loads(x) for x in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert [r["status"] for r in rows] == ["approved", "needs_review"] and rows[1]["issues"][0]["code"]


def test_write_outputs_and_review_queue(tmp_path):
    p = pipe()
    ds = [p.process(CORPUS / n) for n in ("01_acme_clean.pdf", "06_acme_math_error.pdf", "09_acme_exact_duplicate.pdf")]
    counts = write_outputs(ds, tmp_path, "xero")
    assert counts == {"approved": 1, "needs_review": 1, "duplicate": 1}
    assert len(list(csv.reader((tmp_path / "approved.csv").open()))) == 6
    q = json.loads((tmp_path / "review_queue.json").read_text())
    assert any("TOTAL_MISMATCH" in w for item in q for w in item["why"]) and "report" in (tmp_path / "report.md").read_text().lower()


def test_config_override_from_json(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"review_new_vendors": False, "tolerance_abs": "0.10", "unknown_key": 1}))
    c = load_config(f)
    assert c.review_new_vendors is False and str(c.tolerance_abs) == "0.10"


def test_cli_end_to_end(tmp_path, capsys):
    out = tmp_path / "out"
    assert cli_main(["approve-vendor", "Acme Web Services Ltd", "--bank", "GB29 NWBK 6016 1331 9268 19", "--out", str(out)]) == 0
    assert cli_main(["run", str(CORPUS), "--out", str(out), "--preset", "quickbooks"]) == 0
    assert (out / "approved.csv").exists() and (out / "audit.jsonl").exists() and (out / "ledger.jsonl").exists()
    # second run of the same folder: everything already seen is a duplicate, nothing is approved twice
    assert cli_main(["run", str(CORPUS), "--out", str(out)]) == 0
    assert "'approved': 0" in capsys.readouterr().out


# ---- GPT adapter with a fake client: same safety net, different reader
from invoiceflow.extractors import GPTVisionExtractor  # noqa: E402


def test_gpt_extractor_sends_images_forces_function_and_marks_document_untrusted():
    client = FakeOpenAIClient(dict(GOOD), dict(GOOD))
    raw = GPTVisionExtractor(client).extract(CORPUS / "01_acme_clean.pdf")
    call = client.calls[0]
    assert call["tool_choice"]["function"]["name"] == "record_invoice" and "untrusted" in call["messages"][0]["content"]
    assert call["messages"][1]["content"][0]["type"] == "image_url" and raw["method"] == "gpt-vision" and "alt" in raw and raw["doc_text"]


def test_gpt_output_matching_the_document_is_approved():
    d = pipe(GPTVisionExtractor(FakeOpenAIClient(dict(GOOD), dict(GOOD)))).process(CORPUS / "01_acme_clean.pdf")
    assert d.status is Status.APPROVED and d.method == "gpt-vision"


def test_gpt_digit_error_and_invented_number_never_reach_approved():
    for bad in (dict(GOOD, total="$1,100.25"), dict(GOOD, invoice_number="INV-9999-FAKE")):
        d = pipe(GPTVisionExtractor(FakeOpenAIClient(bad, dict(GOOD)))).process(CORPUS / "01_acme_clean.pdf")
        assert d.status is Status.REVIEW


def test_gpt_down_falls_back_to_rules_and_it_is_recorded():
    ex = FallbackExtractor(GPTVisionExtractor(FakeOpenAIClient(boom=True)), TextLayerExtractor())
    d = pipe(ex).process(CORPUS / "01_acme_clean.pdf")
    assert d.status is Status.APPROVED and "fallback after RuntimeError" in d.method


def test_gpt_without_tool_call_raises_so_fallback_can_take_over():
    c = FakeOpenAIClient()
    c.chat.completions.create = lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))])
    try:
        GPTVisionExtractor(c).extract(CORPUS / "01_acme_clean.pdf")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "record_invoice" in str(e)
