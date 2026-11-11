"""Generates a synthetic invoice corpus (all fictional vendors) plus truth.json with the EXPECTED routing.
Run: python samples/generate.py   -> samples/corpus/*.pdf and samples/truth.json"""
import json
import shutil
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "corpus"
D = Decimal
Q = D("0.01")

LAYOUTS = {
    "A": dict(title="INVOICE", num="Invoice No.", date="Date:", due="Due Date:", sub="Subtotal", disc="Discount", tax="Tax ({r}%)", tot="Total"),
    "B": dict(title="Rechnung / Invoice", num="Invoice Number:", date="Invoice Date:", due="Payment due:", sub="Net total", disc="Discount", tax="VAT {r}%", tot="Total due"),
    "C": dict(title="TAX INVOICE", num="Inv #", date="Date:", due="Due:", sub="Subtotal", disc="Discount", tax="GST {r}%", tot="Amount due"),
}


def money(v, style, cur):
    s = f"{v:,.2f}"
    if style == "eu":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    pre = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "INR "}[cur]
    return f"{pre}{s}"


def build(path, vendor, lay, number, date, due, cur, style, lines, rate, discount=D(0), bank=None, fault=None, no_number=False):
    L = LAYOUTS[lay]
    sub = sum((q * u for _, q, u in lines), D(0)).quantize(Q)
    tax = ((sub - discount) * D(rate) / 100).quantize(Q, ROUND_HALF_UP)
    total = (sub - discount + tax).quantize(Q)
    shown_total = total + D(fault) if fault else total
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    page = 1

    def header(first):
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, H - 50, vendor)
        c.setFont("Helvetica", 9)
        c.drawString(50, H - 63, "12 Example Street, Sampletown")
        c.setFont("Helvetica-Bold", 16)
        c.drawRightString(W - 50, H - 50, L["title"])
        c.setFont("Helvetica", 10)
        y = H - 100
        if first:
            if not no_number:
                c.drawString(50, y, f"{L['num']} {number}")
                y -= 14
            c.drawString(50, y, f"{L['date']} {date}")
            y -= 14
            c.drawString(50, y, f"{L['due']} {due}")
            y -= 14
            c.drawString(50, y, "Bill to: Sample Customer Ltd")
            y -= 30
        else:
            c.drawString(50, y, f"Page {page}")
            c.drawString(120, y, "(continued)")
            y -= 20
        return y

    def table_header(y):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, "Description")
        c.drawRightString(360, y, "Qty")
        c.drawRightString(440, y, "Unit Price")
        c.drawRightString(W - 50, y, "Amount")
        c.setFont("Helvetica", 10)
        return y - 16

    y = table_header(header(True))
    for desc, q, u in lines:
        if y < 150:
            c.showPage()
            page += 1
            y = table_header(header(False))
        c.drawString(50, y, desc)
        c.drawRightString(360, y, f"{q:g}")
        c.drawRightString(440, y, money(u, style, cur))
        c.drawRightString(W - 50, y, money((q * u).quantize(Q), style, cur))
        y -= 15
    y -= 10
    c.setFont("Helvetica", 10)
    for label, val in ((L["sub"], sub), (L["disc"], -discount if discount else None), (L["tax"].format(r=rate), tax), (L["tot"], shown_total)):
        if val is None:
            continue
        c.drawString(330, y, label)
        c.drawRightString(W - 50, y, money(val, style, cur))
        y -= 15
    if bank:
        c.drawString(50, y - 15, f"IBAN: {bank}")
    c.save()
    return {"vendor": vendor, "invoice_number": None if no_number else number, "total": str(shown_total), "currency": cur}


def scan_only(src, dst):
    pix = fitz.open(str(src))[0].get_pixmap(dpi=130)
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pg.insert_image(pg.rect, stream=pix.tobytes("png"))
    doc.save(str(dst))


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    items = lambda *rows: [(d, D(str(q)), D(str(u))) for d, q, u in rows]
    base = items(("Website maintenance (hours)", 6, "85.00"), ("Hosting, annual", 1, "240.00"), ("SSL certificate", 2, "35.50"), ("Support call-out", 3, "60.00"), ("Domain renewal", 1, "18.00"))
    truth = {}

    def add(name, status, why, **kw):
        info = build(OUT / name, **kw)
        truth[name] = {"expected_status": status, "why": why, **info}

    add("01_acme_clean.pdf", "approved", "clean baseline", vendor="Acme Web Services Ltd", lay="A", number="INV-2026-0412", date="12 Oct 2026", due="11 Nov 2026",
        cur="USD", style="en", lines=base, rate=8, bank="GB29NWBK60161331926819")
    add("02_nordlicht_eu.pdf", "approved", "EUR, decimal comma, dotted dates, VAT", vendor="Nordlicht Software GmbH", lay="B", number="RE-88213", date="12.10.2026", due="11.11.2026",
        cur="EUR", style="eu", lines=items(("Beratung (Stunden)", 14, "120.00"), ("Lizenz Jahresgebuehr", 1, "1499.00"), ("Reisekosten", 1, "212.40")), rate=19, bank="DE89370400440532013000")
    many = [(f"Part SKU-{i:03d} fastener kit", D(str(1 + i % 4)), D("12.75") + D(i)) for i in range(1, 61)]
    add("03_bluepeak_multipage.pdf", "approved", "60 line items over two pages with a repeated header", vendor="BluePeak Industrial Supply Inc", lay="A", number="BP-5521", date="2026-10-20", due="2026-11-19",
        cur="USD", style="en", lines=many, rate=7, bank="US64SVBKUS6S3300958879")
    add("04_harbor_discount.pdf", "approved", "discount line, INR, GST", vendor="Harbor Logistics Pvt Ltd", lay="C", number="HL/26/0099", date="05 Oct 2026", due="04 Nov 2026",
        cur="INR", style="en", lines=items(("Freight Chennai-Pune", 4, "8200.00"), ("Handling", 4, "450.00")), rate=18, discount=D("1500.00"), bank="IN2200123456789")
    add("05_cedar_vat.pdf", "approved", "GBP, VAT 20%", vendor="Cedar & Pine Design Ltd", lay="B", number="CP-1077", date="October 28, 2026", due="November 27, 2026",
        cur="GBP", style="en", lines=items(("Logo design", 1, "450.00"), ("Brand guidelines", 1, "320.00")), rate=20, bank="GB82WEST12345698765432")
    add("06_acme_math_error.pdf", "needs_review", "printed total is 90.00 too high", vendor="Acme Web Services Ltd", lay="A", number="INV-2026-0430", date="14 Oct 2026", due="13 Nov 2026",
        cur="USD", style="en", lines=base, rate=8, bank="GB29NWBK60161331926819", fault="90.00")
    add("07_missing_number.pdf", "needs_review", "no invoice number printed", vendor="Acme Web Services Ltd", lay="A", number="X", date="15 Oct 2026", due="14 Nov 2026",
        cur="USD", style="en", lines=base[:3], rate=8, bank="GB29NWBK60161331926819", no_number=True)
    add("08_ambiguous_date.pdf", "needs_review", "03/04/2026 could be 3 April or 4 March", vendor="Cedar & Pine Design Ltd", lay="A", number="CP-1099", date="03/04/2026", due="03/05/2026",
        cur="GBP", style="en", lines=items(("Poster print run", 2, "130.00")), rate=20, bank="GB82WEST12345698765432")
    shutil.copy(OUT / "01_acme_clean.pdf", OUT / "09_acme_exact_duplicate.pdf")
    truth["09_acme_exact_duplicate.pdf"] = {"expected_status": "duplicate", "why": "byte-identical resend of 01", **{k: truth["01_acme_clean.pdf"][k] for k in ("vendor", "invoice_number", "total", "currency")}}
    add("10_acme_near_duplicate.pdf", "needs_review", "same vendor and amount, invoice number differs by one digit", vendor="Acme Web Services Ltd", lay="A", number="INV-2026-0413", date="13 Oct 2026", due="12 Nov 2026",
        cur="USD", style="en", lines=base, rate=8, bank="GB29NWBK60161331926819")
    add("11_bluepeak_bank_change.pdf", "needs_review", "bank account differs from the one on file", vendor="BluePeak Industrial Supply Inc", lay="A", number="BP-5560", date="2026-10-29", due="2026-11-28",
        cur="USD", style="en", lines=items(("Safety gloves, box", 10, "14.20"), ("Pallet wrap", 4, "22.00")), rate=7, bank="US11NEWBANK00998877")
    add("12_zenith_round_new_vendor.pdf", "needs_review", "new vendor and a round 5,000.00 total", vendor="Zenith Consulting LLC", lay="C", number="ZC-0001", date="01 Nov 2026", due="01 Dec 2026",
        cur="USD", style="en", lines=items(("Strategy retainer", 1, "4237.29")), rate=18, bank="US55ZENITH00112233")
    add("13_harbor_scan_only.pdf", "needs_review", "image-only scan: no text layer to verify against", vendor="Harbor Logistics Pvt Ltd", lay="C", number="HL/26/0102", date="30 Oct 2026", due="29 Nov 2026",
        cur="INR", style="en", lines=items(("Freight Pune-Chennai", 2, "8300.00")), rate=18, bank="IN2200123456789")
    tmp = OUT / "_scan_src.pdf"
    tmp.write_bytes((OUT / "13_harbor_scan_only.pdf").read_bytes())
    scan_only(tmp, OUT / "13_harbor_scan_only.pdf")
    tmp.unlink()
    add("14_cedar_due_before_date.pdf", "needs_review", "due date earlier than invoice date", vendor="Cedar & Pine Design Ltd", lay="B", number="CP-1101", date="02 Nov 2026", due="02 Oct 2026",
        cur="GBP", style="en", lines=items(("Flyer design", 3, "75.00")), rate=20, bank="GB82WEST12345698765432")
    (OUT.parent / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    print(len(truth), "invoices written")


if __name__ == "__main__":
    main()
