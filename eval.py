"""Scores the pipeline on the synthetic corpus. The metric that matters is the AUTO-APPROVED ERROR RATE
(wrong data that reached 'approved'), not raw field accuracy. Corpus is synthetic and clean: read the numbers that way.
Usage: python eval.py            (rule-based extractor, free)
       python eval.py --llm      (Claude vision, needs ANTHROPIC_API_KEY, costs money)"""
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from invoiceflow.config import Config  # noqa: E402
from invoiceflow.extractors import ClaudeVisionExtractor, FallbackExtractor, TextLayerExtractor  # noqa: E402
from invoiceflow.ledger import Ledger  # noqa: E402
from invoiceflow.normalize import norm_number, normalize_vendor  # noqa: E402
from invoiceflow.pipeline import Pipeline  # noqa: E402
from invoiceflow.validate import VendorMemory  # noqa: E402

ROOT = Path(__file__).parent
SEED = [("Acme Web Services Ltd", "GB29NWBK60161331926819"), ("Nordlicht Software GmbH", "DE89370400440532013000"),
        ("BluePeak Industrial Supply Inc", "US64SVBKUS6S3300958879"), ("Harbor Logistics Pvt Ltd", "IN2200123456789"),
        ("Cedar & Pine Design Ltd", "GB82WEST12345698765432")]


def run(extractor):
    truth = json.loads((ROOT / "samples" / "truth.json").read_text(encoding="utf-8"))
    mem = VendorMemory()
    for v, b in SEED:
        mem.remember(v, b)
    pipe = Pipeline(extractor, Config(), Ledger(), mem, None, today=date(2026, 11, 6))
    decisions = {d.file: d for d in pipe.process_folder(ROOT / "samples" / "corpus")}
    rows, wrong_status, approved_wrong, approved = [], 0, 0, 0
    for name, t in sorted(truth.items()):
        d = decisions[name]
        got = d.status.value
        ok = got == t["expected_status"]
        wrong_status += not ok
        err = ""
        if got == "approved":
            approved += 1
            bad = []
            if normalize_vendor(d.invoice.vendor) != normalize_vendor(t["vendor"]):
                bad.append("vendor")
            if norm_number(d.invoice.invoice_number) != norm_number(t["invoice_number"]):
                bad.append("number")
            if d.invoice.total != Decimal(t["total"]):
                bad.append("total")
            if bad:
                approved_wrong += 1
                err = "WRONG:" + ",".join(bad)
        codes = ",".join(sorted({i.code for i in d.issues if i.severity == "block"}))
        rows.append((name, t["expected_status"], got, "ok" if ok else "MISMATCH", err, codes))
    print(f"{'file':36} {'expected':13} {'got':13} {'route':9} {'data':12} blocking issues")
    for r in rows:
        print(f"{r[0]:36} {r[1]:13} {r[2]:13} {r[3]:9} {r[4]:12} {r[5]}")
    methods = {}
    for d in decisions.values():
        key = "FALLBACK to rules" if "fallback" in d.method else d.method
        methods[key] = methods.get(key, 0) + 1
    print(f"\nextractor actually used: {methods}")
    print(f"routed correctly: {len(rows) - wrong_status}/{len(rows)}")
    print(f"auto-approved: {approved}; auto-approved with wrong data: {approved_wrong}  (auto-approved error rate {approved_wrong}/{approved})")
    return wrong_status, approved_wrong, methods


if __name__ == "__main__":
    if "--llm" in sys.argv:
        import anthropic
        ex = FallbackExtractor(ClaudeVisionExtractor(anthropic.Anthropic()), TextLayerExtractor())
    else:
        ex = TextLayerExtractor()
    bad_route, bad_data, methods = run(ex)
    if "--llm" in sys.argv and any("FALLBACK" in k for k in methods):
        print("\nNOT A LIVE RESULT: some files silently fell back to the rule-based extractor.")
        raise SystemExit(3)
    raise SystemExit(1 if (bad_route or bad_data) else 0)
