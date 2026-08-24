from __future__ import annotations

from pathlib import Path

from amr_preprocess.models import DocClass, ExtractedDocument, RawDocument, TextBlock


def extract(raw: RawDocument) -> ExtractedDocument:
    text = Path(raw.bytes_path).read_text(encoding="utf-8", errors="replace")
    blocks = []
    for i, para in enumerate(text.split("\n\n")):
        para = para.strip()
        if para:
            kind = "heading" if i == 0 and len(para) < 80 else "paragraph"
            blocks.append(TextBlock(block_id=f"t{i}", type=kind, text=para, page=1))
    return ExtractedDocument(
        doc_id=raw.doc_id,
        parent_doc_id=raw.parent_doc_id,
        source_uri=raw.source_uri,
        filename=raw.filename,
        doc_class=DocClass.TEXT,
        mime_type=raw.mime_type,
        blocks=blocks,
        page_count=1,
        metadata=raw.metadata,
    )
