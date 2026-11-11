# Invoice extraction: what matters, and how this tool answers it (2026-11-06)

Method: 5 web searches. Most sources are vendor blogs, so treat specifics as practitioner claims, not measured benchmarks. No independent accuracy numbers were found. Anything this tool claims about its own accuracy must come from its own test corpus, and says so.

## How people usually build it
1. **Template/zone OCR** (Docparser, Parseur style): fast to set up, breaks whenever a vendor changes layout or a table is longer than the template.
2. **OCR engine + rules/ML** (Textract, Document AI, Azure, ABBYY, Rossum, Veryfi): good on headers; line-item tables are the weak spot.
3. **LLM or vision-LLM extraction** with a JSON schema: handles layout variety, but hallucinates and makes digit-level mistakes.
4. **Hybrid (current best practice per practitioners):** OCR/text layer for structured fields, LLM for edge cases, and validation on everything.

## Pain points that actually matter (and the design answer)

| Pain point (from sources) | Why it hurts | Design answer in this tool |
|---|---|---|
| LLM invents values: vision models fabricate a plausible invoice number when it is not visible | A fake ID reaches accounting silently | **Grounding gate:** a value must literally appear in the document text layer; ungrounded critical fields are routed to review. Images with no text layer use a **two-pass consensus** check instead. |
| Digit-level errors (a total changing 4,532 to 4,523 in ~1-3% of LLM extractions, vendor-reported) | Wrong payments, hard to spot | **Arithmetic gate:** totals are recomputed from line items in code and never trusted from the model. Mismatch = review. |
| Multi-page tables: rows missing/duplicated, repeated headers, pages out of order | Missing line items | Page-aware extraction, repeated-header stripping, duplicate-row detection, and a line-sum-vs-subtotal check that catches dropped rows. |
| Layout variety across vendors; templates break | Constant maintenance | No templates. LLM adapter + rule-based fallback, same schema. |
| Confidence thresholds treated as final | Either too much manual work or silent errors | **Per-field criticality routing:** totals, invoice number, vendor, bank details need a higher bar than metadata. Thresholds are config, not constants. |
| Duplicates, including one-digit-changed invoice numbers | Overpayment | **Exact + near-duplicate detection** (normalised vendor, amount, date window, invoice-number edit distance 1). |
| Fraud signals (round amounts, never-seen vendors, split invoices) | Found only at audit | **Risk flags** for round-dollar totals, new vendor, and bank-detail changes against a vendor memory file. Flags route to review, they never auto-block silently. |
| Locale: decimal comma vs point, ambiguous 03/04/2026 dates | Imports rewrite amounts or swap day/month | Explicit locale normaliser. **Ambiguous dates are flagged**, never guessed. |
| Import failures: wrong date format or header names for Xero/QuickBooks | Hours lost fixing CSVs | **Export presets** (generic, Xero-style, QuickBooks-style) with date format per preset and plain-number amounts. |
| "90% accuracy is a warning sign" | Remaining errors are the expensive ones | The headline metric is **auto-approved error rate**, not raw field accuracy. The tool is built to send doubtful items to people. |
| Approval rules in people's heads | Inconsistent decisions | Rules in a config file, plus an append-only audit log of every decision with a reason. |
| Untrusted input | Invoice text can contain instructions | Document text is treated as data; the model may only call one extraction tool. |

## Positioning vs the market
Big vendors sell accuracy. This tool sells **trust**: nothing reaches your books unchecked, every flag says why, and the auto-approve error rate is measured on a labelled corpus. It is a reference build for small teams that want something adaptable (their tool, their rules), not a SaaS replacement.

## Honest limits
- Accuracy numbers will come only from the synthetic corpus in `samples/`, which I generate. Real-world scans (skew, blur, handwriting) are not covered until tested on a client's anonymised samples.
- The Claude vision adapter is unit-tested with a fake client. A live run needs an API key and costs money, so it only happens with the owner's go-ahead.
- No claim of beating Rossum/Veryfi/Textract. No named-client results.

## Sources
- [10 Invoice Data Extraction Challenges & AI Solutions](https://invoicedataextraction.com/blog/invoice-data-extraction-challenges-ai-solutions-2025)
- [Overcoming Common Challenges in Invoice Data Extraction (Veryfi)](https://www.veryfi.com/invoice-automation-invoice-processing/)
- [Multi-page invoice processing guide (KlearStack)](https://klearstack.com/?p=5083)
- [Invoice OCR error handling](https://invoicedataextraction.com/blog/invoice-ocr-error-handling)
- [How AI-powered OCR transforms invoice processing](https://everworker.ai/blog/ai_ocr_invoice_processing_cfo_automation)
- [OCR vs LLM for invoice processing](https://raftlabs.com/blog/ocr-vs-llm-invoice-processing)
- [Receipt document understanding benchmark (arXiv)](https://arxiv.org/pdf/2605.22413)
- [OCR hallucinations in MLLMs (NeurIPS 2025)](https://neurips.cc/virtual/2025/poster/117155)
- [Xero CSV import errors](https://invoicedataextraction.com/blog/xero-csv-import-errors)
- [Getting extracted data into an ERP](https://www.lido.app/blog/how-to-get-extracted-data-into-erp)
