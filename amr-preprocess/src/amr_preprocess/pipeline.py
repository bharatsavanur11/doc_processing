from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from amr_preprocess.artifacts import ArtifactStore
from amr_preprocess.extractors import extract_document
from amr_preprocess.ingest import ingest_bytes
from amr_preprocess.ingest.loader import content_hash
from amr_preprocess.models import ExtractedDocument, ProcessedDocument, RunManifest
from amr_preprocess.normalize import chunk_llm_context, normalize_document
from amr_preprocess.validate import validate_processed

_SUPPORTED = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".xlsx",
    ".csv",
    ".eml",
    ".msg",
    ".txt",
    ".md",
}


def collect_inputs(path: Path) -> list[Path]:
    path = path.expanduser().resolve()
    if path.is_file():
        return [path]
    return [
        p
        for p in sorted(path.rglob("*"))
        if p.is_file() and p.suffix.lower() in _SUPPORTED
    ]


def process_path(
    source: Path,
    artifacts_root: Path,
    *,
    render_pages: bool = True,
    llm_context: bool = False,
    llm_max_tokens: int | None = None,
) -> tuple[RunManifest, Path, list[ProcessedDocument]]:
    inputs = collect_inputs(source)
    if not inputs:
        raise FileNotFoundError(f"no supported documents under {source}")
    store = ArtifactStore(artifacts_root)
    manifest, run_dir = store.new_run([str(p) for p in inputs])
    processed_docs: list[ProcessedDocument] = []
    started = datetime.now(timezone.utc)

    queue: list[tuple[Path | None, bytes | None, dict]] = [
        (p, None, {"source_uri": str(p), "filename": p.name, "parent": None})
        for p in inputs
    ]
    seen: set[str] = set()
    pending_children: dict[str, list[str]] = {}

    while queue:
        path, data, meta = queue.pop(0)
        payload = path.read_bytes() if path is not None else (data or b"")
        doc_id = content_hash(payload)
        if doc_id in seen:
            parent = meta.get("parent")
            if parent:
                pending_children.setdefault(parent, []).append(doc_id)
            continue
        seen.add(doc_id)
        raw = ingest_bytes(
            payload,
            source_uri=meta["source_uri"],
            filename=meta["filename"],
            dest_dir=store.raw_dir(run_dir, doc_id),
            parent_doc_id=meta.get("parent"),
            mime_type=meta.get("mime_type"),
        )
        extracted = extract_document(
            raw,
            pages_dir=store.pages_dir(run_dir, raw.doc_id),
            render_pages=render_pages,
        )
        for att in extracted.attachments:
            queue.append(
                (
                    None,
                    att.data,
                    {
                        "source_uri": f"{raw.source_uri}#{att.filename}",
                        "filename": att.filename,
                        "parent": raw.doc_id,
                        "mime_type": att.mime_type,
                    },
                )
            )
        processed = normalize_document(extracted)
        errors = validate_processed(processed)
        if errors:
            processed.warnings.extend(errors)
        store.save_documents(run_dir, extracted, processed)
        if llm_context:
            store.save_llm_context(
                run_dir,
                processed.doc_id,
                chunk_llm_context(processed, max_tokens=llm_max_tokens),
            )
        processed_docs.append(processed)
        manifest.documents.append(processed.doc_id)
        manifest.warnings.extend(processed.warnings)

    by_parent: dict[str, list[str]] = dict(pending_children)
    for doc in processed_docs:
        if doc.parent_doc_id:
            by_parent.setdefault(doc.parent_doc_id, []).append(doc.doc_id)
    if by_parent:
        for key, ids in list(by_parent.items()):
            by_parent[key] = list(dict.fromkeys(ids))
        for doc in processed_docs:
            kids = by_parent.get(doc.doc_id, [])
            if not kids:
                continue
            doc.children = kids
            extracted_path = run_dir / "docs" / f"{doc.doc_id}.extracted.json"
            extracted = ExtractedDocument.model_validate_json(
                extracted_path.read_text(encoding="utf-8")
            )
            extracted.children = kids
            store.save_documents(run_dir, extracted, doc)

    finished = datetime.now(timezone.utc)
    manifest.finished_at = finished.isoformat()
    manifest.status = "ok"
    manifest.elapsed_ms = int((finished - started).total_seconds() * 1000)
    store.write_manifest(run_dir, manifest)
    return manifest, run_dir, processed_docs
