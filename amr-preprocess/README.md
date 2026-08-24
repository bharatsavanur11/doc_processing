# AMR document preprocessing

CLI pipeline that turns review-pack files (PDF, PPTX, DOCX, XLSX/CSV, EML/MSG, text) into a single `ProcessedDocument` contract, plus an eval harness that scores extraction quality against golden fixtures.

## Install

```bash
cd amr-preprocess
# The workspace path contains a colon, so create the venv outside it:
python3.12 -m venv /tmp/amr-preprocess-venv
source /tmp/amr-preprocess-venv/bin/activate
pip install -e ".[dev]"
# Optional: TableFormer + OCR fallback for decks and scanned PDFs
pip install -e ".[docling]"
```

Python 3.10+ is required. Docling is an optional extra (`AMR_DOCLING=0` disables it even if installed).

Docling downloads its layout/TableFormer/OCR models (hundreds of MB) on first
conversion; prefetch with `docling-tools models download` for offline use. OCR
runs only for scanned PDFs and for deck pages with no usable text layer.

## Commands

```bash
amr-preprocess sample --dest samples
amr-preprocess process samples --out artifacts/runs
amr-preprocess process ../financial-reports --out artifacts/runs
amr-preprocess eval --fixtures evals/fixtures --config evals/config.yaml
```

`process` writes `artifacts/runs/<run_id>/` with raw bytes, extracted JSON, normalized Markdown, a run manifest, and page PNGs (the ColPali retrieval hook).

Add `--llm-context` to also write prompt-ready markdown (`<doc_id>.llm.md`): tables and figure notes interleaved at their page position, `<!-- page N -->` anchors for citation, and inline low-confidence flags. `--llm-max-tokens 8000` splits large documents into page-aligned `.llm.partNN.md` chunks (~4 chars/token estimate).

## Web UI

```bash
pip install -e ".[ui]"
streamlit run "$(pwd)/app.py"   # absolute path needed (workspace path contains a colon)
```

Upload documents in the browser, then inspect extracted content per document: markdown/text blocks, tables (with extraction method and confidence), page renders, figures, metadata, and warnings. Email attachments appear nested under their parent message. Each upload creates a normal pipeline run under `artifacts/ui-runs/`, and the full `ProcessedDocument` JSON is downloadable.

Prefer native `.pptx` when the deck contains real PowerPoint tables. If tables are drawn as shapes (common in earnings slides), process the PDF export so the deck router can use spatial/Docling extraction.

## Routing

PDFs are classified before extraction:

| Class | Signal | Path |
| --- | --- | --- |
| report | InDesign/EDGAR or dense text | PyMuPDF text + tables; Docling TableFormer if confidence is low; else spatial reconstruction |
| deck | PowerPoint producer or sparse text | PyMuPDF text + spatial tables; optional Docling (OCR + TableFormer) if the extra is installed |
| scanned | mostly empty text layer | Docling OCR if the extra is installed; otherwise flagged |
| pptx | native `.pptx` | `python-pptx` (prefer this over PDF-exported decks) |

Emails re-ingest attachments as child documents with `parent_doc_id`.

## Extending

- New format: add an extractor and register it in `extractors/router.py`, plus one fixture under `evals/fixtures/<case>/`.
- New quality check: add a function in `scorers.py` and a threshold in `evals/config.yaml`.
