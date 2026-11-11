"""Exports. Amounts are always plain numbers with a point, dates follow the preset. Column names for the accounting
presets are STYLE presets: check them against the import template of your own account before a real import."""
import csv
import json
from pathlib import Path

PRESETS = {
    "generic": {"date": "%Y-%m-%d", "cols": ["vendor", "invoice_number", "invoice_date", "due_date", "currency", "subtotal", "tax", "total", "description", "qty", "unit_price", "line_amount"]},
    "xero": {"date": "%d/%m/%Y", "cols": ["*ContactName", "*InvoiceNumber", "*InvoiceDate", "*DueDate", "Description", "*Quantity", "*UnitAmount", "Currency"]},
    "quickbooks": {"date": "%m/%d/%Y", "cols": ["Bill No", "Vendor", "Bill Date", "Due Date", "Item Description", "Item Quantity", "Item Rate", "Item Amount", "Currency"]},
}


def _d(d, fmt):
    return d.strftime(fmt) if d else ""


def _n(x):
    return "" if x is None else format(x, "f")


def rows_for(inv, preset):
    p = PRESETS[preset]
    f = p["date"]
    lines = inv.lines or [None]
    out = []
    for ln in lines:
        desc = ln.description if ln else ""
        qty, unit, amt = (ln.qty, ln.unit_price, ln.amount) if ln else (None, None, inv.total)
        if preset == "generic":
            out.append([inv.vendor, inv.invoice_number, _d(inv.invoice_date, f), _d(inv.due_date, f), inv.currency or "",
                        _n(inv.subtotal), _n(inv.tax), _n(inv.total), desc, _n(qty), _n(unit), _n(amt)])
        elif preset == "xero":
            out.append([inv.vendor, inv.invoice_number, _d(inv.invoice_date, f), _d(inv.due_date, f), desc, _n(qty if ln else 1), _n(unit if ln else inv.total), inv.currency or ""])
        else:
            out.append([inv.invoice_number, inv.vendor, _d(inv.invoice_date, f), _d(inv.due_date, f), desc, _n(qty), _n(unit), _n(amt), inv.currency or ""])
    return out


def write_outputs(decisions, outdir, preset="generic"):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    approved = [d for d in decisions if d.status.value == "approved"]
    with (out / "approved.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(PRESETS[preset]["cols"])
        for d in approved:
            w.writerows(rows_for(d.invoice, preset))
    queue = [{"file": d.file, "status": d.status.value, "vendor": d.invoice.vendor, "invoice_number": d.invoice.invoice_number,
              "total": _n(d.invoice.total), "why": [f"{i.code}: {i.message}" for i in d.issues if i.severity == "block"],
              "notes": [f"{i.code}: {i.message}" for i in d.issues if i.severity == "warn"]}
             for d in decisions if d.status.value != "approved"]
    (out / "review_queue.json").write_text(json.dumps(queue, indent=1), encoding="utf-8")
    counts = {s: sum(1 for d in decisions if d.status.value == s) for s in ("approved", "needs_review", "duplicate")}
    lines = ["# Batch report", "", f"Processed {len(decisions)} files: {counts['approved']} approved, {counts['needs_review']} need review, {counts['duplicate']} duplicates.", ""]
    for q in queue:
        lines.append(f"- **{q['file']}** ({q['status']}): " + "; ".join(q["why"]))
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return counts
