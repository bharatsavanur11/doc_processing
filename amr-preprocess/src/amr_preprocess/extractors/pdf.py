from __future__ import annotations

import re
import statistics
from pathlib import Path

import pymupdf

from amr_preprocess.extractors.docling import DoclingExtractor, split_header
from amr_preprocess.extractors.figures import classify_image, link_figures
from amr_preprocess.extractors.spatial_table import extract_spatial_tables, score_rows
from amr_preprocess.models import (
    BBox,
    DocClass,
    ExtractedDocument,
    ExtractedTable,
    FigureAsset,
    RawDocument,
    TextBlock,
)

_PPT_HINTS = ("powerpoint", "pdfmaker", "keynote", "google slides", "libreoffice impress")
_REPORT_HINTS = ("indesign", "edgar", "acrobat distiller", "prince")


def classify_pdf(doc: pymupdf.Document) -> tuple[DocClass, dict]:
    producer = (doc.metadata.get("producer") or "").lower()
    creator = (doc.metadata.get("creator") or "").lower()
    blob = f"{producer} {creator}"
    text_lens = [len(page.get_text().strip()) for page in doc]
    median = int(statistics.median(text_lens)) if text_lens else 0
    empty_ratio = (
        sum(1 for t in text_lens if t < 50) / max(len(text_lens), 1)
    )
    info = {
        "producer": doc.metadata.get("producer"),
        "creator": doc.metadata.get("creator"),
        "median_chars": median,
        "empty_page_ratio": round(empty_ratio, 3),
        "page_count": len(doc),
    }
    if empty_ratio > 0.6:
        return DocClass.SCANNED, info
    if any(h in blob for h in _PPT_HINTS) or (median < 1200 and len(doc) <= 80):
        return DocClass.DECK, info
    if any(h in blob for h in _REPORT_HINTS) or median >= 2000:
        return DocClass.REPORT, info
    if median < 1200:
        return DocClass.DECK, info
    return DocClass.REPORT, info


def extract(
    raw: RawDocument,
    *,
    pages_dir: Path,
    render_pages: bool = True,
) -> ExtractedDocument:
    doc = pymupdf.open(raw.bytes_path)
    if doc.needs_pass:
        page_count = doc.page_count
        doc.close()
        return ExtractedDocument(
            doc_id=raw.doc_id,
            parent_doc_id=raw.parent_doc_id,
            source_uri=raw.source_uri,
            filename=raw.filename,
            doc_class=DocClass.UNKNOWN,
            mime_type=raw.mime_type,
            page_count=page_count,
            metadata=dict(raw.metadata),
            warnings=["password-protected PDF; extraction skipped"],
        )
    doc_class, class_info = classify_pdf(doc)
    warnings: list[str] = []
    blocks: list[TextBlock] = []
    tables: list[ExtractedTable] = []
    figures: list[FigureAsset] = []
    page_images: list[str] = []

    pages_dir.mkdir(parents=True, exist_ok=True)
    # OCR is expensive, so decks only opt in when at least one page has no
    # usable text layer (tables pasted as images).
    needs_ocr = doc_class == DocClass.SCANNED or (
        doc_class == DocClass.DECK
        and any(len(page.get_text().strip()) < 50 for page in doc)
    )
    docling = DoclingExtractor(
        Path(raw.bytes_path),
        ocr=needs_ocr,
        cell_matching=doc_class == DocClass.REPORT,
    )

    for i, page in enumerate(doc):
        page_no = i + 1
        _append_text_blocks(blocks, page, page_no)
        page_tables, page_warn = _extract_page_tables(
            page, page_no, doc_class, docling
        )
        tables.extend(page_tables)
        warnings.extend(page_warn)
        figures.extend(_extract_figures(doc, page, page_no, pages_dir))
        if render_pages:
            pix = page.get_pixmap(dpi=72)
            dest = pages_dir / f"page-{page_no:03d}.png"
            pix.save(str(dest))
            page_images.append(str(dest))

    dl_error = docling.convert_warning()
    if dl_error:
        warnings.append(dl_error)

    if doc_class == DocClass.SCANNED:
        if docling.available():
            if not dl_error:
                pages_with_text = {b.page for b in blocks}
                blocks.extend(
                    b for b in docling.text_blocks() if b.page not in pages_with_text
                )
                blocks.sort(key=lambda b: b.page or 0)
            if not tables:
                warnings.append("scanned PDF: Docling OCR found no tables")
        else:
            warnings.append(
                "scanned PDF detected; install amr-preprocess[docling] for OCR"
            )

    links = link_figures(figures, blocks)
    extracted = ExtractedDocument(
        doc_id=raw.doc_id,
        parent_doc_id=raw.parent_doc_id,
        source_uri=raw.source_uri,
        filename=raw.filename,
        doc_class=doc_class,
        mime_type=raw.mime_type,
        blocks=blocks,
        tables=tables,
        figures=figures,
        figure_links=links,
        page_count=len(doc),
        page_image_paths=page_images,
        metadata={**raw.metadata, **class_info},
        warnings=warnings,
    )
    doc.close()
    return extracted


def _append_text_blocks(blocks: list[TextBlock], page: pymupdf.Page, page_no: int) -> None:
    data = page.get_text("dict")
    for bi, block in enumerate(data.get("blocks", [])):
        if block.get("type") != 0:
            continue
        lines = []
        for line in block.get("lines", []):
            text = " ".join(s.get("text", "") for s in line.get("spans", [])).strip()
            if text:
                lines.append(text)
        body = "\n".join(lines).strip()
        if not body:
            continue
        x0, y0, x1, y1 = block.get("bbox", (0, 0, 0, 0))
        size = 0.0
        spans = [
            s
            for line in block.get("lines", [])
            for s in line.get("spans", [])
        ]
        if spans:
            size = max(s.get("size", 0) for s in spans)
        kind = "heading" if size >= 16 else "paragraph"
        if re.match(r"^\s*(figure|fig\.|chart|table)\s+\d+", body, re.I):
            kind = "caption"
        blocks.append(
            TextBlock(
                block_id=f"p{page_no}_b{bi}",
                type=kind,
                text=body,
                page=page_no,
                bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1, page=page_no),
            )
        )


def _extract_page_tables(
    page: pymupdf.Page,
    page_no: int,
    doc_class: DocClass,
    docling: DoclingExtractor,
) -> tuple[list[ExtractedTable], list[str]]:
    warnings: list[str] = []
    pymu_tables = _pymupdf_tables(page, page_no)
    pymu_best = max((t.confidence for t in pymu_tables), default=0.0)
    need_spatial = doc_class == DocClass.DECK or pymu_best < 0.7 or (
        not pymu_tables and _looks_tabular(page)
    )
    spatial = extract_spatial_tables(page, page_no) if need_spatial else []
    spatial_best = max((t.confidence for t in spatial), default=0.0)
    chosen: list[ExtractedTable] = []
    want_docling = (
        doc_class in {DocClass.DECK, DocClass.SCANNED}
        or pymu_best < 0.7
    ) and (pymu_tables or spatial or _looks_tabular(page) or doc_class == DocClass.SCANNED)
    dl_tables = docling.tables_for_page(page_no) if want_docling else None

    if doc_class == DocClass.SCANNED:
        if dl_tables:
            return dl_tables, warnings
        return (spatial if spatial_best >= pymu_best else pymu_tables), warnings

    if doc_class == DocClass.DECK:
        # Pick the highest-confidence candidate set; Docling wins ties since
        # TableFormer preserves cell structure the heuristics cannot.
        dl_best = max((t.confidence for t in dl_tables), default=0.0) if dl_tables else 0.0
        best = max(dl_best, spatial_best, pymu_best)
        if dl_tables and dl_best >= best:
            chosen = dl_tables
        else:
            if dl_tables == [] and docling.convert_warning() is None:
                warnings.append(f"page {page_no}: Docling returned no tables")
            chosen = spatial if spatial_best >= pymu_best else pymu_tables
        if chosen and max(t.confidence for t in chosen) < 0.7:
            warnings.append(
                f"page {page_no}: low-confidence deck table "
                f"(method={chosen[0].extraction_method})"
            )
    else:
        if pymu_best >= 0.7:
            chosen = pymu_tables
        elif dl_tables:
            chosen = dl_tables
        elif spatial_best > pymu_best:
            chosen = spatial
            if pymu_tables:
                warnings.append(
                    f"page {page_no}: PyMuPDF table confidence {pymu_best:.2f}; "
                    "used spatial reconstruction"
                )
        else:
            chosen = pymu_tables
            if chosen and pymu_best < 0.7:
                if not docling.available():
                    warnings.append(
                        f"page {page_no}: table confidence {pymu_best:.2f}; "
                        "install amr-preprocess[docling] for TableFormer fallback"
                    )
                elif docling.convert_warning() is None:
                    warnings.append(
                        f"page {page_no}: table confidence {pymu_best:.2f}; "
                        "Docling returned no tables"
                    )

    return chosen, warnings


def _pymupdf_tables(page: pymupdf.Page, page_no: int) -> list[ExtractedTable]:
    out: list[ExtractedTable] = []
    try:
        finder = page.find_tables()
    except Exception:
        return out
    for ti, table in enumerate(finder.tables or []):
        data = table.extract() or []
        rows = [[(c or "").strip() for c in row] for row in data]
        headers, body = split_header(rows)
        bbox = getattr(table, "bbox", None)
        out.append(
            ExtractedTable(
                table_id=f"p{page_no}_t{ti}",
                page=page_no,
                headers=headers,
                rows=body,
                extraction_method="pymupdf",
                confidence=score_rows(rows),
                bbox=_bbox_from(bbox, page_no),
            )
        )
    return out


def _bbox_from(bbox, page_no: int) -> BBox | None:
    if not bbox or len(bbox) != 4:
        return None
    x0, y0, x1, y1 = bbox
    return BBox(x0=x0, y0=y0, x1=x1, y1=y1, page=page_no)


def _looks_tabular(page: pymupdf.Page) -> bool:
    text = page.get_text()
    numbers = re.findall(r"\d[\d,.]{2,}", text)
    return len(numbers) >= 8


def _extract_figures(
    doc: pymupdf.Document,
    page: pymupdf.Page,
    page_no: int,
    pages_dir: Path,
) -> list[FigureAsset]:
    figures: list[FigureAsset] = []
    images = page.get_images(full=True)
    for ii, img in enumerate(images):
        xref = img[0]
        try:
            info = doc.extract_image(xref)
        except Exception:
            continue
        w, h = info.get("width", 0), info.get("height", 0)
        kind = classify_image(width=w, height=h, page_image_count=len(images))
        dest = None
        if kind == "data_bearing":
            dest = pages_dir / f"fig-p{page_no:03d}-{ii}.{info.get('ext', 'png')}"
            dest.write_bytes(info["image"])
        figures.append(
            FigureAsset(
                figure_id=f"p{page_no}_img{ii}",
                page=page_no,
                image_path=str(dest) if dest else None,
                kind=kind,
            )
        )
    return figures
