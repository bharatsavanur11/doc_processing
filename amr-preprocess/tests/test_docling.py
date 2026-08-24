from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from amr_preprocess.extractors.docling import (
    DoclingExtractor,
    _bbox,
    grid_from_table,
    split_header,
)
from amr_preprocess.extractors.pdf import extract
from amr_preprocess.models import ExtractedTable, RawDocument, TextBlock
from amr_preprocess.samples import write_samples

DOCLING_INSTALLED = importlib.util.find_spec("docling") is not None


def _raw(pdf_path: Path, doc_id: str = "doc") -> RawDocument:
    return RawDocument(
        doc_id=doc_id,
        source_uri=str(pdf_path),
        mime_type="application/pdf",
        filename=pdf_path.name,
        bytes_path=str(pdf_path),
        size_bytes=pdf_path.stat().st_size,
    )


def _scanned_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


class _FakeDocling:
    """Stand-in for DoclingExtractor with scripted outputs."""

    def __init__(
        self,
        tables_by_page: dict[int, list[ExtractedTable]] | None = None,
        blocks: list[TextBlock] | None = None,
        error: str | None = None,
        installed: bool = True,
    ) -> None:
        self._tables = tables_by_page or {}
        self._blocks = blocks or []
        self._error = error
        self._installed = installed

    def __call__(self, *args, **kwargs):  # constructor stand-in
        return self

    def available(self) -> bool:
        return self._installed

    def tables_for_page(self, page_no: int) -> list[ExtractedTable] | None:
        if not self._installed:
            return None
        return self._tables.get(page_no, [])

    def text_blocks(self) -> list[TextBlock]:
        return self._blocks

    def convert_warning(self) -> str | None:
        return self._error


def test_grid_from_table_cells() -> None:
    cells = [
        SimpleNamespace(
            text=text,
            start_row_offset_idx=r,
            start_col_offset_idx=c,
            end_row_offset_idx=r + 1,
            end_col_offset_idx=c + 1,
        )
        for text, r, c in [
            ("Metric", 0, 0),
            ("Q2", 0, 1),
            ("Revenue", 1, 0),
            ("412", 1, 1),
        ]
    ]
    table = SimpleNamespace(
        data=SimpleNamespace(num_rows=2, num_cols=2, table_cells=cells)
    )
    grid = grid_from_table(table)
    headers, rows = split_header(grid)
    assert headers == [["Metric", "Q2"]]
    assert rows == [["Revenue", "412"]]


def test_split_header_allows_digit_labels() -> None:
    fiscal = [["Segment", "FY25", "FY24"], ["Subscription", "1200", "1000"]]
    headers, rows = split_header(fiscal)
    assert headers == [["Segment", "FY25", "FY24"]]
    assert rows == [["Subscription", "1200", "1000"]]

    numeric_first = [["Revenue", "412", "9%"], ["OpMargin", "31%", "120bps"]]
    headers, rows = split_header(numeric_first)
    assert headers == []
    assert len(rows) == 2

    currency = [["Region", "$1,200", "(300)"]]
    assert split_header(currency) == ([], currency)


def test_bbox_bottom_left_origin_flipped() -> None:
    box = SimpleNamespace(l=10, r=100, t=700, b=650, coord_origin="BOTTOMLEFT")
    mapped = _bbox(box, page_no=1, page_height=792)
    assert mapped is not None
    assert mapped.y0 == 92  # 792 - 700
    assert mapped.y1 == 142  # 792 - 650

    top_left = SimpleNamespace(l=10, r=100, t=50, b=90, coord_origin="TOPLEFT")
    mapped = _bbox(top_left, page_no=1, page_height=792)
    assert mapped is not None
    assert (mapped.y0, mapped.y1) == (50, 90)


def test_docling_disabled_without_extra(monkeypatch) -> None:
    monkeypatch.setenv("AMR_DOCLING", "0")
    assert DoclingExtractor().available() is False


def test_convert_warning_never_triggers_conversion(tmp_path: Path) -> None:
    extractor = DoclingExtractor(tmp_path / "missing.pdf")
    assert extractor.convert_warning() is None
    assert extractor._output is None


def test_deck_prefers_docling_on_tie(monkeypatch, tmp_path: Path) -> None:
    fake = _FakeDocling(
        tables_by_page={
            1: [
                ExtractedTable(
                    table_id="p1_dl0",
                    page=1,
                    headers=[["Metric", "Q2", "YoY"]],
                    rows=[["Revenue", "412", "9%"]],
                    extraction_method="docling",
                    confidence=1.0,
                )
            ]
        }
    )
    monkeypatch.setattr("amr_preprocess.extractors.pdf.DoclingExtractor", fake)
    samples = tmp_path / "samples"
    write_samples(samples)
    extracted = extract(
        _raw(samples / "acme-earnings-deck.pdf"),
        pages_dir=tmp_path / "pages",
        render_pages=False,
    )
    assert extracted.tables
    assert extracted.tables[0].extraction_method == "docling"


def test_deck_low_confidence_docling_loses(monkeypatch, tmp_path: Path) -> None:
    fake = _FakeDocling(
        tables_by_page={
            1: [
                ExtractedTable(
                    table_id="p1_dl0",
                    page=1,
                    rows=[["garbled", ""]],
                    extraction_method="docling",
                    confidence=0.05,
                )
            ]
        }
    )
    monkeypatch.setattr("amr_preprocess.extractors.pdf.DoclingExtractor", fake)
    samples = tmp_path / "samples"
    write_samples(samples)
    extracted = extract(
        _raw(samples / "acme-earnings-deck.pdf"),
        pages_dir=tmp_path / "pages",
        render_pages=False,
    )
    assert extracted.tables
    assert extracted.tables[0].extraction_method in {"spatial", "pymupdf"}


def test_scanned_merges_ocr_text_per_page(monkeypatch, tmp_path: Path) -> None:
    fake = _FakeDocling(
        blocks=[
            TextBlock(block_id="dl_p1_b0", text="OCR page one", page=1),
            TextBlock(block_id="dl_p2_b0", text="OCR page two", page=2),
        ]
    )
    monkeypatch.setattr("amr_preprocess.extractors.pdf.DoclingExtractor", fake)
    pdf_path = _scanned_pdf(tmp_path / "scan.pdf")
    extracted = extract(
        _raw(pdf_path), pages_dir=tmp_path / "pages", render_pages=False
    )
    assert extracted.doc_class.value == "scanned"
    texts = [b.text for b in extracted.blocks]
    assert "OCR page one" in texts and "OCR page two" in texts
    assert any("found no tables" in w for w in extracted.warnings)


def test_conversion_failure_warned_once(monkeypatch, tmp_path: Path) -> None:
    fake = _FakeDocling(error="Docling conversion failed: boom")
    monkeypatch.setattr("amr_preprocess.extractors.pdf.DoclingExtractor", fake)
    pdf_path = _scanned_pdf(tmp_path / "scan.pdf")
    extracted = extract(
        _raw(pdf_path), pages_dir=tmp_path / "pages", render_pages=False
    )
    failures = [w for w in extracted.warnings if "conversion failed" in w]
    assert len(failures) == 1
    # OCR text from a failed conversion must not leak in
    assert not any("Docling returned no tables" in w for w in extracted.warnings)


def test_scanned_without_docling_flagged(monkeypatch, tmp_path: Path) -> None:
    fake = _FakeDocling(installed=False)
    monkeypatch.setattr("amr_preprocess.extractors.pdf.DoclingExtractor", fake)
    pdf_path = _scanned_pdf(tmp_path / "scan.pdf")
    extracted = extract(
        _raw(pdf_path), pages_dir=tmp_path / "pages", render_pages=False
    )
    assert any("install amr-preprocess[docling]" in w for w in extracted.warnings)


def test_password_protected_pdf_skipped(tmp_path: Path) -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret")
    pdf_path = tmp_path / "locked.pdf"
    doc.save(
        str(pdf_path),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="hunter2",
        owner_pw="hunter2",
    )
    doc.close()
    extracted = extract(
        _raw(pdf_path), pages_dir=tmp_path / "pages", render_pages=False
    )
    assert extracted.doc_class.value == "unknown"
    assert not extracted.blocks and not extracted.tables
    assert any("password-protected" in w for w in extracted.warnings)


@pytest.mark.skipif(not DOCLING_INSTALLED, reason="docling extra not installed")
def test_real_docling_converts_sample_deck(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    write_samples(samples)
    extractor = DoclingExtractor(samples / "acme-earnings-deck.pdf")
    tables = extractor.tables_for_page(1)
    assert extractor.convert_warning() is None
    assert tables is not None
