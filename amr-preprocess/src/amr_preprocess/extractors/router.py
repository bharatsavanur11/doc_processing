from __future__ import annotations

import re
from pathlib import Path

from amr_preprocess.extractors import email_ext, office, pdf, text as text_ext
from amr_preprocess.models import ExtractedDocument, RawDocument

_PDF = "application/pdf"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def extract_document(
    raw: RawDocument,
    *,
    pages_dir: Path,
    render_pages: bool = True,
) -> ExtractedDocument:
    mime = raw.mime_type
    name = raw.filename.lower()

    if mime == _PDF or name.endswith(".pdf"):
        return pdf.extract(raw, pages_dir=pages_dir, render_pages=render_pages)
    if mime == _DOCX or name.endswith(".docx"):
        return office.extract_docx(raw)
    if name.endswith(".doc"):
        doc = office.extract_docx(raw)
        doc.warnings.append("legacy .doc is not parsed natively; convert to .docx")
        doc.doc_class = doc.doc_class
        return doc
    if mime == _PPTX or name.endswith(".pptx"):
        return office.extract_pptx(raw)
    if mime == _XLSX or name.endswith(".xlsx"):
        return office.extract_xlsx(raw)
    if name.endswith(".csv") or mime == "text/csv":
        return office.extract_csv(raw)
    if name.endswith(".eml") or mime in {"message/rfc822", "message/rfc2822"}:
        return email_ext.extract_eml(raw)
    if name.endswith(".msg") or mime == "application/vnd.ms-outlook":
        return email_ext.extract_msg(raw)
    if mime.startswith("text/") or name.endswith((".txt", ".md")):
        return text_ext.extract(raw)

    extracted = text_ext.extract(raw)
    extracted.warnings.append(f"unknown mime {mime}; treated as text")
    return extracted


def looks_like_caption(text: str) -> bool:
    return bool(re.match(r"^\s*(figure|fig\.|chart|table|exhibit)\s+\d+", text, re.I))
