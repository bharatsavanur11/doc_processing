from __future__ import annotations

from amr_preprocess.models import ProcessedDocument


def score_run(doc: ProcessedDocument, expected: dict) -> dict[str, float]:
    return {
        "schema_valid": _schema_valid(doc),
        "doc_class": 1.0 if doc.doc_class.value == expected.get("doc_class") else 0.0,
        "provenance_coverage": _provenance(doc),
        "table_cell_accuracy": _table_accuracy(doc, expected),
        "block_recall": _block_recall(doc, expected),
    }


def _schema_valid(doc: ProcessedDocument) -> float:
    try:
        ProcessedDocument.model_validate(doc.model_dump())
        return 1.0
    except Exception:
        return 0.0


def _provenance(doc: ProcessedDocument) -> float:
    items = list(doc.blocks) + list(doc.tables)
    if not items:
        return 1.0
    covered = sum(1 for item in items if getattr(item, "page", None))
    return covered / len(items)


def _table_accuracy(doc: ProcessedDocument, expected: dict) -> float:
    gold_tables = expected.get("tables") or []
    if not gold_tables:
        return 1.0
    pred_cells = _cell_set(doc.tables)
    gold_cells = set()
    for table in gold_tables:
        for row in (table.get("headers") or []) + (table.get("rows") or []):
            for cell in row:
                text = str(cell).strip()
                if text:
                    gold_cells.add(text)
    if not gold_cells:
        return 1.0
    hit = sum(1 for c in gold_cells if c in pred_cells)
    return hit / len(gold_cells)


def _block_recall(doc: ProcessedDocument, expected: dict) -> float:
    needles = expected.get("must_contain") or []
    if not needles:
        return 1.0
    hay = " ".join(b.text for b in doc.blocks) + "\n" + doc.markdown
    hit = sum(1 for n in needles if n in hay)
    return hit / len(needles)


def _cell_set(tables) -> set[str]:
    cells: set[str] = set()
    for table in tables:
        for row in (table.headers or []) + table.rows:
            for cell in row:
                text = str(cell).strip()
                if text:
                    cells.add(text)
    return cells
