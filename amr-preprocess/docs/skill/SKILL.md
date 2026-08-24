---
name: amr-doc-pipeline
description: Build, port, or extend the AMR document preprocessing pipeline - multi-format extraction (PDF, DOCX, PPTX, XLSX, EML/MSG) into a ProcessedDocument contract with Docling TableFormer/OCR fallback, prompt-ready LLM context output, and a scored eval harness. Use when creating a document extraction pipeline, integrating Docling, extracting tables from financial PDFs or decks, preparing document context for LLMs, or adding extractors, scorers, or fixtures to amr-preprocess.
---

# AMR Document Preprocessing Pipeline

A CLI pipeline that converts review-pack files (PDF, PPTX, DOCX, XLSX/CSV, EML/MSG, text) into a single `ProcessedDocument` contract (structured JSON + normalized Markdown + page/bbox provenance), with optional Docling table/OCR fallback, prompt-ready LLM context output, and golden-fixture evals.

Reference implementation: `amr-preprocess/` (src layout, `amr_preprocess` package). When porting to a new repo, copy the tested source rather than rewriting.

## Architecture

```
ingest (sha256[:16] doc_id, mime sniff)
  -> extractors.router (mime/extension dispatch)
       pdf.py     classify report|deck|scanned -> PyMuPDF + docling.py + spatial_table.py + figures.py
       office.py  docx/pptx/xlsx/csv (native tables, confidence 1.0)
       email_ext  eml/msg; attachments re-queued as child docs (parent_doc_id)
       text.py    txt/md and unknown-type fallback
  -> normalize (clean.py archival markdown; llm_context.py prompt-ready output)
  -> validate + artifacts store (extracted.json, processed.json, .md, .llm.md, pages/*.png, manifest)
  -> eval_runner + scorers vs evals/fixtures thresholds
```

## Non-negotiable rules

1. **Contract first.** All extractors emit `ExtractedDocument`; consumers only see `ProcessedDocument`. Never bypass the contract.
2. **Confidence ladder for tables.** Native > PyMuPDF (keep if >= 0.7) > Docling TableFormer > spatial reconstruction. All methods score with the same shared `score_rows` heuristic so candidates are comparable. Decks pick the highest-confidence set; Docling wins ties.
3. **Optional deps degrade, never break.** Import heavy deps (docling, extract-msg) inside functions; on failure emit a warning once per document, not per page. Status checks like `convert_warning()` must be side-effect-free (must not trigger a conversion).
4. **OCR policy.** Scanned PDFs always; deck pages only when the text layer is < 50 chars (image-only tables); reports never. One Docling conversion per document maximum, converter cached at module level keyed by options.
5. **Coordinate system.** Normalize Docling bottom-left bboxes to PyMuPDF top-left at the adapter boundary using page height. One coordinate system everywhere else.
6. **Header rule.** `split_header`: a header row contains no numeric values. Digit-bearing labels (`FY25`, `Q2`) are headers; numbers/currency/percent (`1200`, `$1,200`, `9%`, `(300)`) mark data rows. Single shared implementation.
7. **Warnings are quality signals.** Password-protected PDFs, missing OCR extra, conversion failures, low-confidence tables - all become explicit warnings propagated to the manifest and LLM context header. Never silent empty output.
8. **Determinism switches.** `AMR_DOCLING=0` disables the model path so evals reproduce across machines.

## Workflow: extending the pipeline

- **New format**: add an extractor emitting `ExtractedDocument`, register in `extractors/router.py`, add one golden fixture under `evals/fixtures/<case>/` with `expected.json` (`filename`, `doc_class`, `must_contain`, `tables`).
- **New quality check**: add a function to `scorers.py`, a threshold to `evals/config.yaml`.
- **New table method**: emit `ExtractedTable` with `extraction_method` and `score_rows` confidence; plug into the ladder in `pdf.py:_extract_page_tables`, do not bypass it.
- **Testing optional deps**: monkeypatch a fake adapter class implementing `available/tables_for_page/text_blocks/convert_warning`; gate the real integration test with `skipif` on importability.

## Verification gates

After any change:

```bash
pytest -q                                  # all pass (docling integration test skips without the extra)
amr-preprocess sample && amr-preprocess eval   # all 5 threshold gates PASS
amr-preprocess process samples --llm-context --no-render-pages  # .llm.md has page anchors + confidence flags
```

Environment: Python 3.10+; create the venv OUTSIDE paths containing special characters (colons break venv creation). Docling downloads models (hundreds of MB) on first conversion; `docling-tools models download` prefetches.

## Additional resources

- Full requirements, design rationale, module specs, and known edge cases: [reference.md](reference.md)
