"""HTTP service: `uvicorn invoiceflow.api:app --host 0.0.0.0 --port 8000`   (docs at /docs)

  GET  /health            liveness + which reader is active
  POST /invoices          multipart upload of one PDF/PNG/JPG -> the full decision: approved | needs_review | duplicate,
                          the extracted fields, and every gate that fired with a plain reason. Only the gates can approve.
  POST /vendors/approve   {name, bank?}  record a vendor a human has checked (new-vendor and changed-bank gates use this)

Reader: the free rule-based text-layer reader by default; set INVOICEFLOW_LLM=claude (+ ANTHROPIC_API_KEY) for Claude vision.
State (duplicate ledger, vendor memory, append-only audit log) lives in INVOICEFLOW_DATA_DIR (default ./out); mount it as a volume.
Optional auth: set INVOICEFLOW_API_TOKEN and send `Authorization: Bearer <token>` (/health stays open).
Uploads are size-capped, extension-allowlisted and written under a generated name, never the client's file name."""
import hmac
import os
import tempfile
import threading
import uuid
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from .audit import AuditLog
from .config import load_config
from .ledger import Ledger
from .pipeline import Pipeline
from .validate import VendorMemory

ALLOWED = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_BYTES = int(os.environ.get("INVOICEFLOW_MAX_BYTES", 10 * 1024 * 1024))


class VendorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    bank: Optional[str] = Field(default=None, max_length=64)


def build_extractor():
    from .extractors import ClaudeVisionExtractor, FallbackExtractor, TextLayerExtractor
    if os.environ.get("INVOICEFLOW_LLM", "").lower() == "claude":
        import anthropic
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("INVOICEFLOW_LLM=claude but ANTHROPIC_API_KEY is not set")
        return FallbackExtractor(ClaudeVisionExtractor(anthropic.Anthropic()), TextLayerExtractor()), "claude-vision+text-layer"
    return TextLayerExtractor(), "text-layer (rule-based)"


def create_app(extractor, reader_name: str, data_dir, cfg=None, token: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="InvoiceFlow", version="1.0")
    data = Path(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    memory = VendorMemory(data / "vendors.json")
    pipe = Pipeline(extractor, cfg or load_config(None), Ledger(data / "ledger.jsonl"), memory, AuditLog(data / "audit.jsonl"))
    lock = threading.Lock()  # the ledger and audit files are append-only but check-then-write must not interleave

    def auth(authorization: str = Header(default="")):
        if token and not hmac.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(401, "missing or wrong bearer token")

    @app.get("/health")
    def health():
        return {"status": "ok", "reader": reader_name}

    @app.post("/invoices", dependencies=[Depends(auth)])
    def upload(file: UploadFile = File(...)):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED:
            raise HTTPException(415, f"unsupported file type {suffix or '(none)'}; send one of {sorted(ALLOWED)}")
        body = file.file.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise HTTPException(413, f"file larger than {MAX_BYTES} bytes")
        if not body:
            raise HTTPException(400, "empty file")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{uuid.uuid4().hex}{suffix}"
            path.write_bytes(body)
            with lock:
                d = pipe.process(path)
        out = jsonable_encoder(asdict(d), custom_encoder={Decimal: str})  # money stays an exact string, never a float
        out["file"] = Path(file.filename).name  # report the client's name, but only after it has been reduced to a base name
        return out

    @app.post("/vendors/approve", dependencies=[Depends(auth)])
    def approve_vendor(v: VendorIn):
        with lock:
            memory.remember(v.name, v.bank.replace(" ", "").upper() if v.bank else None)
        return {"vendor": v.name, "remembered": True}

    return app


def __getattr__(name):  # `uvicorn invoiceflow.api:app` builds the real app on first access only
    if name == "app":
        ext, name_ = build_extractor()
        return create_app(ext, name_, os.environ.get("INVOICEFLOW_DATA_DIR", "out"), token=os.environ.get("INVOICEFLOW_API_TOKEN"))
    raise AttributeError(name)
