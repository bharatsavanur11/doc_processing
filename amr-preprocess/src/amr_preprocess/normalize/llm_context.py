from __future__ import annotations

from dataclasses import dataclass

from amr_preprocess.models import ProcessedDocument

LOW_CONFIDENCE = 0.7
_MAX_HEADER_WARNINGS = 8


@dataclass
class ContextChunk:
    text: str
    page_start: int
    page_end: int
    token_estimate: int


def to_llm_context(doc: ProcessedDocument) -> str:
    """Render a ProcessedDocument as prompt-ready markdown.

    Unlike ProcessedDocument.markdown (which appends all tables at the end),
    this interleaves tables and figure notes at their page position, adds
    page anchors for citation, and flags low-confidence tables inline.
    """
    sections = _page_sections(doc)
    parts = [_header(doc)]
    parts.extend(text for _page, text in sections)
    return "\n\n".join(parts).strip() + "\n"


def chunk_llm_context(
    doc: ProcessedDocument, max_tokens: int | None = None
) -> list[ContextChunk]:
    """Split the LLM context into page-aligned chunks under a token budget.

    Token counts are estimated at ~4 characters per token, so budgets are
    approximate. With max_tokens=None the whole document is one chunk.
    """
    sections = _page_sections(doc)
    if not sections:
        text = to_llm_context(doc)
        return [ContextChunk(text, 0, 0, _tokens(text))]

    if max_tokens is None:
        text = to_llm_context(doc)
        return [
            ContextChunk(text, sections[0][0], sections[-1][0], _tokens(text))
        ]

    groups: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    budget = 0
    for page, text in sections:
        cost = _tokens(text)
        if current and budget + cost > max_tokens:
            groups.append(current)
            current, budget = [], 0
        current.append((page, text))
        budget += cost
    if current:
        groups.append(current)

    chunks: list[ContextChunk] = []
    for i, group in enumerate(groups, start=1):
        start, end = group[0][0], group[-1][0]
        header = _header(doc, part=(i, len(groups)), pages=(start, end))
        body = "\n\n".join(text for _page, text in group)
        text = f"{header}\n\n{body}".strip() + "\n"
        chunks.append(ContextChunk(text, start, end, _tokens(text)))
    return chunks


def _header(
    doc: ProcessedDocument,
    part: tuple[int, int] | None = None,
    pages: tuple[int, int] | None = None,
) -> str:
    lines = [f"# {doc.filename}"]
    meta = f"<!-- doc:{doc.doc_id} class:{doc.doc_class.value} pages:{doc.page_count} -->"
    lines.append(meta)
    if part and part[1] > 1:
        lines.append(
            f"*Part {part[0]} of {part[1]} (pages {pages[0]}-{pages[1]} "
            f"of {doc.page_count}).*"
        )
    warnings = list(dict.fromkeys(doc.warnings))[:_MAX_HEADER_WARNINGS]
    if warnings:
        lines.append("> Extraction notes: " + "; ".join(warnings))
    return "\n".join(lines)


def _page_sections(doc: ProcessedDocument) -> list[tuple[int, str]]:
    """One markdown section per page: text blocks, then tables, then figures."""
    pages: set[int] = set()
    for b in doc.blocks:
        pages.add(b.page or 0)
    for t in doc.tables:
        pages.add(t.page or 0)
    for f in doc.figures:
        if f.kind == "data_bearing":
            pages.add(f.page or 0)

    sections: list[tuple[int, str]] = []
    for page in sorted(pages):
        parts: list[str] = []
        if page > 0:
            parts.append(f"<!-- page {page} -->")
        for b in doc.blocks:
            if (b.page or 0) != page:
                continue
            parts.append(f"## {b.text}" if b.type == "heading" else b.text)
        for t in doc.tables:
            if (t.page or 0) != page:
                continue
            parts.append(_table_section(t))
        for f in doc.figures:
            if f.kind != "data_bearing" or (f.page or 0) != page:
                continue
            note = f"[Figure {f.figure_id} on page {f.page}"
            if f.caption:
                note += f": {f.caption}"
            if f.image_path:
                note += f"; image: {f.image_path}"
            note += "]"
            parts.append(note)
        if parts:
            sections.append((page, "\n\n".join(parts)))
    return sections


def _table_section(t) -> str:
    from amr_preprocess.normalize.clean import table_to_markdown

    label = f"**Table {t.table_id}** ({t.extraction_method}, confidence {t.confidence:.2f}"
    if t.confidence < LOW_CONFIDENCE:
        label += "; low confidence, verify against the source"
    label += ")"
    lines = [label]
    if t.caption:
        lines.append(f"*{t.caption}*")
    grid_md = table_to_markdown(t)
    if grid_md:
        lines.append(grid_md)
    return "\n\n".join(lines)


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)
