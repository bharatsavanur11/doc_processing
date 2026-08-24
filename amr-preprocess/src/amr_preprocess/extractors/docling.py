from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from amr_preprocess.extractors.spatial_table import score_rows
from amr_preprocess.models import BBox, ExtractedTable, TextBlock

_CONVERTERS: dict[tuple[bool, bool], Any] = {}


class DoclingExtractor:
    """Optional IBM Docling adapter for table structure and scanned-PDF OCR.

    Enabled when the ``docling`` extra is installed. Set ``AMR_DOCLING=0`` to
    skip even if the package is present (useful for fast evals).
    """

    def __init__(
        self,
        pdf_path: Path | None = None,
        *,
        ocr: bool = False,
        cell_matching: bool = True,
    ) -> None:
        self.pdf_path = Path(pdf_path) if pdf_path else None
        self.ocr = ocr
        self.cell_matching = cell_matching
        self._output: _DoclingOutput | None = None

    def available(self) -> bool:
        if os.environ.get("AMR_DOCLING", "1").strip().lower() in {"0", "false", "off"}:
            return False
        try:
            import docling  # noqa: F401
        except ImportError:
            return False
        return True

    def tables_for_page(self, page_no: int) -> list[ExtractedTable] | None:
        out = self._ensure()
        if out is None:
            return None
        return out.tables_by_page.get(page_no, [])

    def text_blocks(self) -> list[TextBlock]:
        out = self._ensure()
        if out is None:
            return []
        return out.blocks

    def convert_warning(self) -> str | None:
        """Error from a conversion that already ran; never triggers a conversion."""
        if self._output is None:
            return None
        return self._output.error

    def _ensure(self) -> _DoclingOutput | None:
        if not self.available() or self.pdf_path is None:
            return None
        if self._output is None:
            self._output = convert_pdf(
                self.pdf_path,
                ocr=self.ocr,
                cell_matching=self.cell_matching,
            )
        return self._output


class _DoclingOutput:
    def __init__(
        self,
        tables_by_page: dict[int, list[ExtractedTable]],
        blocks: list[TextBlock],
        error: str | None = None,
    ) -> None:
        self.tables_by_page = tables_by_page
        self.blocks = blocks
        self.error = error


def convert_pdf(
    pdf_path: Path,
    *,
    ocr: bool = False,
    cell_matching: bool = True,
) -> _DoclingOutput:
    try:
        converter = _converter(ocr=ocr, cell_matching=cell_matching)
        result = converter.convert(str(pdf_path))
        doc = getattr(result, "document", result)
    except Exception as exc:
        return _DoclingOutput({}, [], error=f"Docling conversion failed: {exc}")
    heights = _page_heights(doc)
    return _DoclingOutput(
        tables_by_page=_tables_by_page(doc, heights),
        blocks=_text_blocks(doc, heights),
    )


def _converter(*, ocr: bool, cell_matching: bool) -> Any:
    key = (ocr, cell_matching)
    cached = _CONVERTERS.get(key)
    if cached is not None:
        return cached
    from docling.document_converter import DocumentConverter

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
        from docling.document_converter import PdfFormatOption

        opts = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True)
        tso = getattr(opts, "table_structure_options", None)
        if tso is not None:
            tso.do_cell_matching = cell_matching
            if hasattr(tso, "mode"):
                try:
                    tso.mode = TableFormerMode.ACCURATE
                except Exception:
                    pass
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=opts)
            }
        )
    except Exception:
        converter = DocumentConverter()
    _CONVERTERS[key] = converter
    return converter


def _page_heights(doc: Any) -> dict[int, float]:
    heights: dict[int, float] = {}
    pages = getattr(doc, "pages", None) or {}
    items = pages.items() if hasattr(pages, "items") else enumerate(pages, start=1)
    for key, page in items:
        size = getattr(page, "size", None)
        height = getattr(size, "height", None)
        page_no = getattr(page, "page_no", None)
        try:
            if height:
                heights[int(page_no if page_no is not None else key)] = float(height)
        except (TypeError, ValueError):
            continue
    return heights


def _tables_by_page(doc: Any, heights: dict[int, float]) -> dict[int, list[ExtractedTable]]:
    grouped: dict[int, list[ExtractedTable]] = {}
    tables = list(getattr(doc, "tables", None) or [])
    if not tables and hasattr(doc, "iterate_items"):
        try:
            for item, _level in doc.iterate_items():
                if _is_table(item):
                    tables.append(item)
        except Exception:
            pass
    for table in tables:
        page_no, bbox = _prov(table, heights)
        page_no = page_no or 1
        grid = grid_from_table(table)
        if not grid:
            continue
        headers, rows = split_header(grid)
        idx = len(grouped.get(page_no, []))
        grouped.setdefault(page_no, []).append(
            ExtractedTable(
                table_id=f"p{page_no}_dl{idx}",
                page=page_no,
                caption=_caption(table, doc),
                headers=headers,
                rows=rows,
                extraction_method="docling",
                confidence=score_rows(grid),
                bbox=bbox,
            )
        )
    return grouped


def _text_blocks(doc: Any, heights: dict[int, float]) -> list[TextBlock]:
    items = list(getattr(doc, "texts", None) or [])
    if not items and hasattr(doc, "iterate_items"):
        try:
            items = [item for item, _level in doc.iterate_items() if hasattr(item, "text")]
        except Exception:
            items = []
    blocks: list[TextBlock] = []
    for i, item in enumerate(items):
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        label = str(getattr(item, "label", "") or "").lower()
        if "table" in label:
            continue
        kind = "paragraph"
        if "title" in label or "header" in label:
            kind = "heading"
        elif "caption" in label:
            kind = "caption"
        page_no, bbox = _prov(item, heights)
        blocks.append(
            TextBlock(
                block_id=f"dl_p{page_no or 0}_b{i}",
                type=kind,
                text=text,
                page=page_no,
                bbox=bbox,
            )
        )
    return blocks


def grid_from_table(table: Any) -> list[list[str]]:
    data = getattr(table, "data", table)
    cells = (
        getattr(data, "table_cells", None)
        or getattr(data, "cells", None)
        or []
    )
    n_rows = int(getattr(data, "num_rows", 0) or 0)
    n_cols = int(getattr(data, "num_cols", 0) or 0)
    if cells and (not n_rows or not n_cols):
        n_rows = max((_cell_end_row(c) for c in cells), default=0)
        n_cols = max((_cell_end_col(c) for c in cells), default=0)
    if n_rows and n_cols and cells:
        grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]
        for cell in cells:
            text = (getattr(cell, "text", None) or "").strip()
            r0 = int(getattr(cell, "start_row_offset_idx", 0) or 0)
            c0 = int(getattr(cell, "start_col_offset_idx", 0) or 0)
            r1 = max(_cell_end_row(cell), r0 + 1)
            c1 = max(_cell_end_col(cell), c0 + 1)
            for r in range(r0, min(r1, n_rows)):
                for c in range(c0, min(c1, n_cols)):
                    if not grid[r][c]:
                        grid[r][c] = text
        return [row for row in grid if any(c.strip() for c in row)]
    exported = _export_grid(table)
    if exported:
        return exported
    return []


# Matches cells that are numeric values (possibly with currency, sign,
# thousands separators, or a percent suffix) as opposed to labels like "FY25".
_NUMERIC_CELL = re.compile(r"^[\s$€£(+-]*[\d,.]+[\s%)]*$")


def _is_numeric_cell(cell: str | None) -> bool:
    return bool(cell) and bool(_NUMERIC_CELL.match(str(cell).strip()))


def split_header(rows: list[list[str]]) -> tuple[list[list[str]], list[list[str]]]:
    """Treat the first row as a header when it has no numeric *values*.

    Labels containing digits ("FY25", "Q2") still count as header cells;
    only cells that are numbers/currency/percentages mark a data row.
    """
    if not rows:
        return [], []
    first = rows[0]
    if any((c or "").strip() for c in first) and not any(
        _is_numeric_cell(c) for c in first
    ):
        return [first], rows[1:]
    return [], rows


def _export_grid(table: Any) -> list[list[str]]:
    export = getattr(table, "export_to_dataframe", None)
    if not callable(export):
        return []
    try:
        df = export()
    except TypeError:
        try:
            df = export(doc=None)
        except Exception:
            return []
    except Exception:
        return []
    try:
        headers = ["" if c is None else str(c).strip() for c in list(df.columns)]
        body = [
            ["" if v is None else str(v).strip() for v in row]
            for row in df.astype(str).values.tolist()
        ]
        if headers and any(h and not h.startswith("Unnamed") for h in headers):
            return [headers, *body]
        return body
    except Exception:
        return []


def _is_table(item: Any) -> bool:
    name = type(item).__name__.lower()
    label = str(getattr(item, "label", "") or "").lower()
    return "table" in name or "table" in label or hasattr(item, "export_to_dataframe")


def _cell_end_row(cell: Any) -> int:
    end = getattr(cell, "end_row_offset_idx", None)
    if end is not None:
        return int(end)
    start = int(getattr(cell, "start_row_offset_idx", 0) or 0)
    span = int(getattr(cell, "row_span", 1) or 1)
    return start + span


def _cell_end_col(cell: Any) -> int:
    end = getattr(cell, "end_col_offset_idx", None)
    if end is not None:
        return int(end)
    start = int(getattr(cell, "start_col_offset_idx", 0) or 0)
    span = int(getattr(cell, "col_span", 1) or 1)
    return start + span


def _prov(
    item: Any, heights: dict[int, float] | None = None
) -> tuple[int | None, BBox | None]:
    prov = getattr(item, "prov", None) or []
    if not prov:
        return None, None
    first = prov[0]
    page_no = getattr(first, "page_no", None)
    if page_no is not None:
        page_no = int(page_no)
    bbox = getattr(first, "bbox", None)
    page_height = (heights or {}).get(page_no) if page_no is not None else None
    mapped = _bbox(bbox, page_no, page_height)
    return page_no, mapped


def _bbox(
    bbox: Any, page_no: int | None, page_height: float | None = None
) -> BBox | None:
    if bbox is None:
        return None
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        x0, y0, x1, y1 = bbox
        return BBox(x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1), page=page_no)
    l = getattr(bbox, "l", None)
    r = getattr(bbox, "r", None)
    t = getattr(bbox, "t", None)
    b = getattr(bbox, "b", None)
    if None in (l, r, t, b):
        return None
    top, bottom = float(min(t, b)), float(max(t, b))
    # Docling provenance boxes default to a bottom-left origin; flip to
    # PyMuPDF's top-left convention so figure linking stays meaningful.
    origin = str(getattr(bbox, "coord_origin", "") or "").lower()
    if "bottom" in origin and page_height:
        top, bottom = page_height - bottom, page_height - top
    return BBox(x0=float(l), y0=top, x1=float(r), y1=bottom, page=page_no)


def _caption(table: Any, doc: Any) -> str | None:
    cap = getattr(table, "caption_text", None)
    if callable(cap):
        try:
            cap = cap(doc)
        except TypeError:
            try:
                cap = cap()
            except Exception:
                return None
        except Exception:
            return None
    if isinstance(cap, str) and cap.strip():
        return cap.strip()
    return None
