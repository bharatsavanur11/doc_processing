from __future__ import annotations

from pathlib import Path

from amr_preprocess.eval_runner import run_eval
from amr_preprocess.samples import write_eval_fixtures
from amr_preprocess.scorers import score_run
from amr_preprocess.models import DocClass, ProcessedDocument, TextBlock


def test_scorers_perfect_match() -> None:
    doc = ProcessedDocument(
        doc_id="abc",
        source_uri="x",
        filename="notes.docx",
        doc_class=DocClass.DOCX,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        markdown="Churn risk",
        blocks=[TextBlock(block_id="b1", type="paragraph", text="Churn risk", page=1)],
    )
    scores = score_run(doc, {"doc_class": "docx", "must_contain": ["Churn"], "tables": []})
    assert scores["schema_valid"] == 1.0
    assert scores["doc_class"] == 1.0
    assert scores["block_recall"] == 1.0
    assert scores["provenance_coverage"] == 1.0


def test_eval_fixtures(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    write_eval_fixtures(fixtures)
    config = Path(__file__).resolve().parents[1] / "evals" / "config.yaml"
    report = run_eval(fixtures, config)
    by_name = {row["name"]: row for row in report["scores"]}
    assert by_name["schema_valid"]["pass"]
    assert by_name["doc_class"]["pass"]
    assert by_name["block_recall"]["pass"]
    assert by_name["table_cell_accuracy"]["score"] >= 0.6
