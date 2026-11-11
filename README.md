# invoiceflow: invoice data extraction that does not trust itself (reference build)

Reads supplier invoices (PDF or image), extracts the fields and line items, **checks them in code**, and sends only verified invoices to your books. Everything doubtful goes to a review queue with a plain reason. Built as a reference system; not delivered for a paying client.

The design target is not raw accuracy. It is the **auto-approved error rate**: wrong data that reaches "approved". See `RESEARCH.md` for the pain points this answers and the sources.

## How it works
```
file -> Extractor (Claude vision, 2 independent readings | rule-based text layer fallback)
     -> normalise (locale-safe amounts and dates; ambiguity is flagged, never guessed)
     -> gates:  required fields | arithmetic recomputed in code | grounding in the document text
                | two-reading consensus (image-only docs) | per-field confidence | dates | currency
                | duplicates (exact + one-digit-changed) | new vendor | changed bank details | round amounts
     -> APPROVED -> approved.csv (generic / Xero-style / QuickBooks-style)
        otherwise -> review_queue.json with the reasons, plus report.md and an append-only audit.jsonl
```
Key idea: the model can only **propose**. Totals are recomputed from line items, every critical value must literally appear in the document text, and image-only documents need two independent readings to agree. A fabricated invoice number or a swapped digit cannot reach "approved".

## Run
```
pip install -r requirements.txt
python samples/generate.py                    # synthetic corpus: 14 fictional invoices + expected routing
python eval.py                                # routing + auto-approved error rate (free, rule-based)
python -m pytest -q                           # 115 tests, no network
python -m invoiceflow.cli approve-vendor "Acme Web Services Ltd" --bank GB29NWBK60161331926819 --out out   (PYTHONPATH=src)
python -m invoiceflow.cli run samples/corpus --out out --preset xero                                       (PYTHONPATH=src)
python -m invoiceflow.cli run <folder> --llm   # Claude vision; needs ANTHROPIC_API_KEY, costs money (eval.py --llm exits 3 if any file silently fell back to the rules)
```
Business rules (tolerances, thresholds, whether new vendors need review) are in `config.py` and can be overridden from a JSON file with `--config`.

## What is measured (and what is not)
- Synthetic corpus, 14 invoices: **14/14 routed as expected; 5 auto-approved, 0 with wrong data**. Covered: clean USD, EUR with decimal comma and dotted dates, a 60-line two-page table with repeated header, discount + GST, GBP VAT, wrong total, missing invoice number, ambiguous date, exact duplicate, one-digit near-duplicate, changed bank account, new vendor + round total, image-only scan, due date before invoice date.
- **Live run with Claude vision (2026-11-06, `python eval.py --llm`, all 14 files read by `claude-sonnet-5-5`, two passes each): 13/14 routed as expected; 6 auto-approved, 0 with wrong data.** The one difference is the image-only scan: both readings agreed and the data was correct (2 x 8,300 + 18% = 19,588), so it was approved; my expectation had assumed the rule-based extractor, which cannot read scans. Set `scans_always_review` in the config if you want every scan checked by a person. Claude's output varies between runs (in one full run a pass produced a value for an invoice number that is not printed on the page, and the grounding and consensus gates blocked it; in a re-check both passes correctly returned null).
- 50 corruption tests flip one digit in total, subtotal, invoice number, date or bank account of the clean invoices: **none was approved**.
- **Not measured:** real-world scans (skew, blur, stamps, handwriting), real vendor layouts, large volumes, the live adapter beyond this one 14-file synthetic run (the 114 unit tests use a fake client). I wrote both the corpus and the rules, so treat the numbers as a regression suite, not proof of accuracy in your environment. The right next step is a trial on 20-50 of your own anonymised invoices.

## Honest limits
- The rule-based fallback only reads digital PDFs with a text layer. Scanned images need the Claude adapter.
- Export presets are style presets: check column names against your own accounting import template before a real import.
- `$` is read as USD; CAD/AUD need a stated currency code.
- No bank or ERP posting: it produces files, not journal entries.

## Layout
`src/invoiceflow/` extractors, normalize, validate (gates), ledger (duplicates), export, audit, pipeline, cli. `samples/` corpus generator. `eval.py` scoring. `tests/` unit, pipeline and fuzz tests.

## Run it as a service (HTTP API + Docker)
```
docker compose up -d --build
curl -s localhost:8000/health
curl -s -X POST localhost:8000/vendors/approve -H 'content-type: application/json' -d '{"name":"Acme Web Services Ltd","bank":"GB29NWBK60161331926819"}'
curl -s -X POST localhost:8000/invoices -F "file=@samples/corpus/01_acme_clean.pdf"     # -> approved | needs_review | duplicate + every gate that fired
```
Interactive docs at `/docs`. Same gates as the CLI, nothing relaxed: only the gates can approve. Amounts are returned as exact strings (never floats).
- Reader: free rule-based text-layer reader by default; `INVOICEFLOW_LLM=claude` + `ANTHROPIC_API_KEY` switches to Claude vision (costs money per invoice).
- State (duplicate ledger, vendor memory, audit log) lives in the `invoiceflow_data` volume (`INVOICEFLOW_DATA_DIR`), so duplicates are caught across requests and restarts.
- Hardening: uploads are extension-allowlisted (pdf/png/jpg) and size-capped (`INVOICEFLOW_MAX_BYTES`, default 10 MB), stored under a generated name, container runs as a non-root user. `INVOICEFLOW_API_TOKEN` requires a bearer token (`/health` stays open).
- A corrupt file is a `needs_review` item with `EXTRACTION_FAILED`, never a 500. 15 API tests (130 total) run with no network; the container was built and smoke-tested (health, vendor approve, approve, duplicate).
- Not done: no rate limiting, no TLS (put it behind your reverse proxy), single-process (a lock serialises the ledger check-then-write), no OCR for scans without Claude vision.
