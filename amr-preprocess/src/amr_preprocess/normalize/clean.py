from __future__ import annotations

import re

from amr_preprocess.models import ExtractedDocument, ExtractedTable, ProcessedDocument, TextBlock


def normalize_document(extracted: ExtractedDocument) -> ProcessedDocument:
    blocks = [_clean_block(b) for b in extracted.blocks]
    blocks = [b for b in blocks if b.text]
    tables = [_clean_table(t) for t in extracted.tables]
    md = to_markdown(blocks, tables, extracted.filename)
    return ProcessedDocument(
        doc_id=extracted.doc_id,
        parent_doc_id=extracted.parent_doc_id,
        source_uri=extracted.source_uri,
        filename=extracted.filename,
        doc_class=extracted.doc_class,
        mime_type=extracted.mime_type,
        markdown=md,
        blocks=blocks,
        tables=tables,
        figures=extracted.figures,
        figure_links=extracted.figure_links,
        page_count=extracted.page_count,
        page_image_paths=extracted.page_image_paths,
        children=extracted.children,
        metadata=extracted.metadata,
        warnings=list(extracted.warnings),
    )


def to_markdown(
    blocks: list[TextBlock],
    tables: list[ExtractedTable],
    title: str,
) -> str:
    parts = [f"# {title}", ""]
    for b in blocks:
        if b.type == "heading":
            parts.append(f"## {b.text}")
        else:
            parts.append(b.text)
        parts.append("")
    for t in tables:
        parts.append(f"### Table {t.table_id}")
        if t.caption:
            parts.append(f"*{t.caption}*")
        grid_md = table_to_markdown(t)
        if grid_md:
            parts.append(grid_md)
            parts.append("")
    return "\n".join(parts).strip() + "\n"


def table_to_markdown(table: ExtractedTable) -> str:
    grid = (table.headers or []) + table.rows
    if not grid:
        return ""
    width = max(len(r) for r in grid)
    norm = [r + [""] * (width - len(r)) for r in grid]
    header = norm[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in norm[1:])
    return "\n".join(lines)


def _clean_block(block: TextBlock) -> TextBlock:
    text = _clean_text(block.text)
    return block.model_copy(update={"text": text})


def _clean_table(table: ExtractedTable) -> ExtractedTable:
    headers = [[_clean_text(c) for c in row] for row in table.headers]
    rows = [[_clean_text(c) for c in row] for row in table.rows]
    return table.model_copy(update={"headers": headers, "rows": rows})


def _clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
