from __future__ import annotations

from pathlib import Path

from amr_preprocess.extractors.pdf import classify_pdf
from amr_preprocess.pipeline import process_path
from amr_preprocess.samples import write_samples

import pymupdf


def test_pdf_class_router(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    write_samples(samples)
    report = pymupdf.open(samples / "acme-annual-report.pdf")
    deck = pymupdf.open(samples / "acme-earnings-deck.pdf")
    report_class, _ = classify_pdf(report)
    deck_class, _ = classify_pdf(deck)
    report.close()
    deck.close()
    assert report_class.value == "report"
    assert deck_class.value == "deck"


def test_process_samples_and_email_children(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    write_samples(samples)
    manifest, run_dir, docs = process_path(samples, tmp_path / "artifacts", render_pages=False)
    assert manifest.status == "ok"
    classes = {d.filename: d.doc_class.value for d in docs}
    assert classes["acme-annual-report.pdf"] == "report"
    assert classes["acme-earnings-deck.pdf"] == "deck"
    assert classes["account-notes.docx"] == "docx"
    assert classes["qbr-slides.pptx"] == "pptx"
    assert classes["pipeline.xlsx"] == "sheet"
    assert classes["review-pack.eml"] == "email"
    email = next(d for d in docs if d.filename == "review-pack.eml")
    assert email.children
    child = next(d for d in docs if d.doc_id == email.children[0])
    assert child.filename == "risks.csv"
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "docs" / f"{email.doc_id}.md").exists()

    _, _, nested = process_path(
        samples / "review-pack.eml", tmp_path / "email-art", render_pages=False
    )
    nested_email = nested[0]
    nested_child = next(d for d in nested if d.doc_id == nested_email.children[0])
    assert nested_child.parent_doc_id == nested_email.doc_id
    assert nested_child.filename == "risks.csv"


def test_native_office_tables(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    write_samples(samples)
    _, _, docs = process_path(
        samples / "account-notes.docx", tmp_path / "artifacts", render_pages=False
    )
    doc = docs[0]
    cells = {c for t in doc.tables for r in (t.headers + t.rows) for c in r}
    assert "Churn" in cells
    assert "High" in cells
