"""HTTP API tests: real rule-based reader on the synthetic corpus, temp data dir, no network."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from invoiceflow import api
from invoiceflow.extractors import TextLayerExtractor

CORPUS = Path(__file__).resolve().parents[1] / "samples" / "corpus"
ACME = {"name": "Acme Web Services Ltd", "bank": "GB29 NWBK 6016 1331 9268 19"}


@pytest.fixture
def client(tmp_path):
    return TestClient(api.create_app(TextLayerExtractor(), "text-layer (rule-based)", tmp_path))


def send(c, name, filename=None, **kw):
    return c.post("/invoices", files={"file": (filename or name, (CORPUS / name).read_bytes(), "application/pdf")}, **kw)


def test_health_names_reader(client):
    assert client.get("/health").json() == {"status": "ok", "reader": "text-layer (rule-based)"}


def test_clean_invoice_approved_after_vendor_known(client):
    assert client.post("/vendors/approve", json=ACME).json()["remembered"] is True
    r = send(client, "01_acme_clean.pdf")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "approved" and j["invoice"]["invoice_number"] == "INV-2026-0412" and j["invoice"]["total"] == "1100.52"
    assert j["file"] == "01_acme_clean.pdf" and len(j["sha256"]) == 64


def test_new_vendor_is_not_auto_approved(client):
    j = send(client, "01_acme_clean.pdf").json()
    assert j["status"] == "needs_review" and any(i["code"] == "NEW_VENDOR" for i in j["issues"])


def test_exact_duplicate_detected_across_requests(client):
    client.post("/vendors/approve", json=ACME)
    assert send(client, "01_acme_clean.pdf").json()["status"] == "approved"
    assert send(client, "01_acme_clean.pdf").json()["status"] == "duplicate"


def test_wrong_total_goes_to_review_with_reason(client):
    client.post("/vendors/approve", json=ACME)
    j = send(client, "06_acme_math_error.pdf").json()
    assert j["status"] == "needs_review" and any(i["severity"] == "block" for i in j["issues"])


def test_rejects_wrong_type_empty_and_oversized(client, monkeypatch):
    assert client.post("/invoices", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert client.post("/invoices", files={"file": ("x.pdf", b"", "application/pdf")}).status_code == 400
    monkeypatch.setattr(api, "MAX_BYTES", 10)
    assert client.post("/invoices", files={"file": ("x.pdf", b"%PDF-" + b"0" * 50, "application/pdf")}).status_code == 413


def test_garbage_pdf_is_a_review_item_not_a_500(client):
    r = client.post("/invoices", files={"file": ("bad.pdf", b"%PDF-1.4 not really a pdf", "application/pdf")})
    assert r.status_code == 200 and r.json()["status"] == "needs_review"
    assert any(i["code"] == "EXTRACTION_FAILED" for i in r.json()["issues"])


def test_client_filename_is_reduced_to_base_name(client):
    j = send(client, "01_acme_clean.pdf", filename="../../etc/evil.pdf").json()
    assert j["file"] == "evil.pdf"


def test_bearer_token_required_when_configured(tmp_path):
    c = TestClient(api.create_app(TextLayerExtractor(), "t", tmp_path, token="s3cret"))
    assert c.get("/health").status_code == 200
    assert send(c, "01_acme_clean.pdf").status_code == 401
    assert c.post("/vendors/approve", json=ACME).status_code == 401
    assert send(c, "01_acme_clean.pdf", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_state_persists_across_app_restarts(tmp_path):
    a = TestClient(api.create_app(TextLayerExtractor(), "t", tmp_path))
    a.post("/vendors/approve", json=ACME)
    assert send(a, "01_acme_clean.pdf").json()["status"] == "approved"
    b = TestClient(api.create_app(TextLayerExtractor(), "t", tmp_path))  # same data dir = same ledger
    assert send(b, "01_acme_clean.pdf").json()["status"] == "duplicate"
