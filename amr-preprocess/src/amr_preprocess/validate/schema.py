from __future__ import annotations

from amr_preprocess.models import ProcessedDocument


def validate_processed(doc: ProcessedDocument) -> list[str]:
    errors: list[str] = []
    if not doc.doc_id:
        errors.append("missing doc_id")
    if not doc.filename:
        errors.append("missing filename")
    if doc.page_count < 0:
        errors.append("invalid page_count")
    for table in doc.tables:
        widths = {len(r) for r in table.rows if r}
        if len(widths) > 3:
            errors.append(f"{table.table_id}: highly ragged columns {widths}")
    return errors
