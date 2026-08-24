# AMR Pipeline Reference

Detailed requirements, design rationale, module specifications, and edge cases for the AMR document preprocessing pipeline. The canonical implementation plan lives at `docs/plan/amr-pipeline-new-repo.plan.md` in the repo.

## Requirements

### Functional

- FR1 - Ingest PDF, DOCX (legacy .doc with warning), PPTX, XLSX, CSV, EML, MSG, TXT/MD; unknown types fall back to text extraction with a warning.
- FR2 - Every input converges on one `ProcessedDocument`: structured JSON + normalized Markdown, page/bbox provenance on every block and table.
- FR3 - PDFs classified (report / deck / scanned) before extraction: empty-page ratio > 0.6 = scanned; PowerPoint producer hints or sparse text = deck; InDesign/EDGAR hints or dense text = report.
- FR4 - Table confidence ladder (native, PyMuPDF, Docling TableFormer, spatial); highest confidence wins, Docling wins deck ties.
- FR5 - OCR only for scanned PDFs and image-only deck pages.
- FR6 - Email attachments re-ingested as child documents with `parent_doc_id`, deduplicated by content hash; parents re-saved when deduped children link back.
- FR7 - Images classified decorative vs data-bearing (size + per-page image count gate); data-bearing saved and caption-linked.
- FR8 - LLM context output: metadata header, deduped warnings blockquote, `<!-- page N -->` anchors, per-page interleaving (blocks, tables, figure notes), low-confidence flags below 0.7, optional page-aligned chunking at ~4 chars/token.
- FR9 - Eval harness: golden fixtures with `expected.json`, five scorers, thresholds in `evals/config.yaml` (schema 1.0, doc_class 0.8, provenance 0.8, table cells 0.6, block recall 0.8), metrics.json per run.
- FR10 - Graceful degradation with explicit warnings; never silent empty output.

### Non-functional

- Local-first, no runtime network calls; Docling models cached locally.
- Deterministic evals via `AMR_DOCLING=0`.
- Max one Docling conversion per document; OCR only when needed; page PNG rendering optional (`--no-render-pages`).
- Python 3.10+; permissive licenses only (Docling is MIT; PyMuPDF is AGPL - acceptable for internal tooling, flag if shipping commercially).
- Every routing branch testable without heavy optional deps.

## Module specifications

### models.py (the contract)

`DocClass` (report/deck/scanned/docx/pptx/sheet/email/text/unknown), `BBox`, `TextBlock` (block_id, type paragraph|heading|caption, text, page, bbox), `ExtractedTable` (table_id, page, caption, headers + rows as list-of-rows, extraction_method, confidence, bbox), `FigureAsset`, `FigureLink`, `RawDocument`, `Attachment` (bytes, excluded from serialization), `ExtractedDocument`, `ProcessedDocument` (adds markdown + pipeline_version), `RunManifest`.

### ingest/loader.py

`content_hash` = sha256 hex[:16]; doc_id is content identity. `sniff_mime`: extension map first, mimetypes fallback, `%PDF-` / `PK` magic bytes last.

### extractors/spatial_table.py

`score_rows(rows) -> 0..1`: fill ratio minus merged-cell penalty (cells with multiple numbers), ragged-width penalty (0.15), long-cell penalty. Used by ALL table methods. Spatial reconstruction: cluster PyMuPDF words by y (gap 6) into lines, flag tabular lines, take longest run, cluster x (gap 18) into columns, drop empty rows/cols, reject if < 3 rows or < 2 cols.

### extractors/docling.py (the hardened adapter)

- `DoclingExtractor(pdf_path, ocr=False, cell_matching=True)`; lazy one-shot conversion in `_ensure`; module-level `_CONVERTERS` cache keyed `(ocr, cell_matching)`.
- `available()`: False if `AMR_DOCLING` in {0,false,off} or import fails.
- `convert_warning()`: returns error only if a conversion already ran - MUST NOT trigger one.
- Converter: `PdfPipelineOptions(do_ocr=..., do_table_structure=True)`, `TableFormerMode.ACCURATE`, `do_cell_matching` per doc class (True for reports); defensive fallback to bare `DocumentConverter()`.
- `_page_heights` from `doc.pages[].size.height`; `_bbox` flips bottom-left origin (`coord_origin` contains "bottom") to top-left: `y0 = H - max(t,b), y1 = H - min(t,b)`.
- `grid_from_table`: cell offsets (start/end row/col idx, or start + span), span fill without overwrite, DataFrame export fallback, drop empty rows.
- `split_header` numeric-cell rule with `_NUMERIC_CELL = ^[\s$€£(+-]*[\d,.]+[\s%)]*$`.

### extractors/pdf.py (routing)

- Password guard first: `doc.needs_pass` -> early return, `doc_class=UNKNOWN`, warning "password-protected PDF; extraction skipped".
- `needs_ocr = scanned or (deck and any page text < 50 chars)`.
- Per page: text blocks (heading if font >= 16pt, caption if matches figure/table regex), table ladder, figure extraction, optional 72dpi page PNG.
- Table selection non-deck: PyMuPDF if >= 0.7; else Docling if it produced tables; else spatial vs PyMuPDF by confidence, with method-specific warnings ("returned no tables" only when conversion succeeded; install hint when extra missing).
- Deck: max-confidence among docling/spatial/pymupdf, Docling wins ties; low-confidence warning below 0.7.
- After loop: Docling conversion error appended once. Scanned: merge `docling.text_blocks()` only for pages missing PyMuPDF text, sort blocks by page, warn if no tables.

### normalize/

- `clean.py`: nbsp/whitespace cleanup, archival `to_markdown` (tables appended at end under `### Table <id>`), shared `table_to_markdown` pipe renderer.
- `llm_context.py`: `to_llm_context(doc)` and `chunk_llm_context(doc, max_tokens)` returning `ContextChunk(text, page_start, page_end, token_estimate)`. Chunks self-describe: "Part i of k (pages a-b of n)". Decorative figures excluded; data-bearing figures rendered as `[Figure <id> on page N: caption; image: path]`.

### pipeline.py + artifacts/store.py + cli.py

BFS queue over inputs and attachments; dedupe by doc_id with parent-child linking (re-save parents whose children deduped). Store writes `raw/`, `docs/` (extracted.json, processed.json, .md, optional .llm.md or .llm.partNN.md), `pages/`, manifest.json. CLI: `process` (`--llm-context`, `--llm-max-tokens`, `--no-render-pages`), `eval`, `sample`.

### evals

`samples.py` generates synthetic fixtures (report PDF with InDesign metadata, deck PDF with PowerPoint metadata, docx/pptx/xlsx/csv/eml/txt). Scorers: schema_valid, doc_class, provenance_coverage, table_cell_accuracy (flat cell-set recall vs gold), block_recall (must_contain needles against blocks + markdown).

## Known edge cases and their handling

| Edge case | Handling |
| --- | --- |
| Digit-bearing header labels (FY25, Q2) | numeric-cell rule in split_header, not "contains digit" |
| Image-only tables on decks | per-page text check enables OCR for the doc |
| Password-protected PDF | early return + warning, doc_class unknown |
| Docling conversion crash | error stored, surfaced once, fallbacks proceed |
| Partially scanned doc | OCR blocks merged only for text-less pages |
| Same attachment twice | content-hash dedupe, both parents linked |
| Unknown mime | text extraction + warning |
| Docling API drift | getattr-defensive adapter + DataFrame fallback |

## Deferred (documented, not built)

Scanned-PDF eval fixture; multi-page table stitching; numeric cell normalization (parenthesized negatives, footnote markers); Docling accuracy benchmark on real financial reports; ColPali visual retrieval branch (page PNGs are the hook); MinerU as alternative adapter if Docling accuracy disappoints.

## Framework selection rationale (2026)

Docling chosen for: MIT license, CPU-only operation, TableFormer strength on borderless/merged financial tables, breadth (email/pptx/audio). Rejected: Marker 2 (weight license revenue threshold; weak on whitespace-aligned tables), MinerU (accuracy leader but GPU-preferred, heavier license), Unstructured (duplicates native extractors, lower table accuracy), hosted APIs (cost, data residency). Vision LLM (Claude) was the original deck-table path and was removed: API cost, nondeterminism, no offline path; may return as a low-confidence-triggered tier 3.
