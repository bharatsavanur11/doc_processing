from __future__ import annotations

from pathlib import Path

from amr_preprocess.models import (
    DocClass,
    ExtractedTable,
    FigureAsset,
    ProcessedDocument,
    TextBlock,
)
from amr_preprocess.normalize import chunk_llm_context, to_llm_context
from amr_preprocess.pipeline import process_path
from amr_preprocess.samples import write_samples


def _doc(**overrides) -> ProcessedDocument:
    base = dict(
        doc_id="d1",
        source_uri="x",
        filename="report.pdf",
        doc_class=DocClass.REPORT,
        mime_type="application/pdf",
        page_count=2,
        blocks=[
            TextBlock(block_id="b1", type="heading", text="Results", page=1),
            TextBlock(block_id="b2", text="Revenue grew strongly.", page=1),
            TextBlock(block_id="b3", text="Guidance unchanged.", page=2),
        ],
        tables=[
            ExtractedTable(
                table_id="p1_t0",
                page=1,
                headers=[["Segment", "FY25"]],
                rows=[["Subscription", "1200"]],
                extraction_method="pymupdf",
                confidence=0.5,
            )
        ],
        figures=[
            FigureAsset(
                figure_id="p2_img0",
                page=2,
                kind="data_bearing",
                image_path="/tmp/fig.png",
                caption="Revenue trend",
            ),
            FigureAsset(figure_id="p1_img1", page=1, kind="decorative"),
        ],
        warnings=["page 1: table confidence 0.50; Docling returned no tables"],
    )
    base.update(overrides)
    return ProcessedDocument(**base)


def test_context_interleaves_by_page() -> None:
    ctx = to_llm_context(_doc())
    p1 = ctx.index("<!-- page 1 -->")
    table = ctx.index("**Table p1_t0**")
    p2 = ctx.index("<!-- page 2 -->")
    figure = ctx.index("[Figure p2_img0")
    assert p1 < table < p2 < figure
    assert "## Results" in ctx
    assert "| Segment | FY25 |" in ctx
    assert "Revenue trend" in ctx and "/tmp/fig.png" in ctx
    # decorative figures stay out of the prompt
    assert "p1_img1" not in ctx


def test_context_flags_low_confidence_and_warnings() -> None:
    ctx = to_llm_context(_doc())
    assert "low confidence, verify against the source" in ctx
    assert "> Extraction notes:" in ctx

    confident = _doc(warnings=[])
    confident.tables[0].confidence = 0.95
    ctx = to_llm_context(confident)
    assert "low confidence" not in ctx
    assert "Extraction notes" not in ctx


def test_chunking_respects_budget_and_pages() -> None:
    blocks = [
        TextBlock(block_id=f"b{p}", text=f"Paragraph on page {p}. " * 40, page=p)
        for p in range(1, 7)
    ]
    doc = _doc(blocks=blocks, tables=[], figures=[], warnings=[], page_count=6)
    chunks = chunk_llm_context(doc, max_tokens=200)
    assert len(chunks) > 1
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 6
    ends = [c.page_end for c in chunks]
    assert ends == sorted(ends)
    for chunk in chunks:
        assert chunk.text.startswith("# report.pdf")
        assert f"Part {chunks.index(chunk) + 1} of {len(chunks)}" in chunk.text

    single = chunk_llm_context(doc, max_tokens=None)
    assert len(single) == 1
    assert single[0].page_start == 1 and single[0].page_end == 6


def test_pipeline_writes_llm_context(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    write_samples(samples)
    _, run_dir, docs = process_path(
        samples / "acme-earnings-deck.pdf",
        tmp_path / "artifacts",
        render_pages=False,
        llm_context=True,
    )
    doc = docs[0]
    llm_md = run_dir / "docs" / f"{doc.doc_id}.llm.md"
    assert llm_md.exists()
    content = llm_md.read_text(encoding="utf-8")
    assert "<!-- page 1 -->" in content
    assert "Q2 FY26 Results" in content
