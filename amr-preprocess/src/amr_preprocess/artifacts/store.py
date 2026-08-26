"""Versioned artifact layout for pipeline runs.

Each run gets its own directory under the artifact root:

    <root>/<run_id>/
        manifest.json
        raw/<doc_id>/<filename>          original bytes
        docs/<doc_id>.extracted.json     ExtractedDocument
        docs/<doc_id>.processed.json     ProcessedDocument
        docs/<doc_id>.md                 archival markdown
        docs/<doc_id>.llm.md             optional prompt-ready context
        docs/<doc_id>.llm.partNN.md      ...or page-aligned chunks
        pages/<doc_id>/page-NNN.png      page renders + figure crops
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

from amr_preprocess.models import ExtractedDocument, ProcessedDocument, RunManifest
from amr_preprocess.normalize.llm_context import ContextChunk


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def new_run(self, inputs: list[str]) -> tuple[RunManifest, Path]:
        started = datetime.now(timezone.utc)
        run_id = f"{started.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
        run_dir = self.root / run_id
        (run_dir / "raw").mkdir(parents=True, exist_ok=True)
        (run_dir / "docs").mkdir(parents=True, exist_ok=True)
        (run_dir / "pages").mkdir(parents=True, exist_ok=True)
        manifest = RunManifest(
            run_id=run_id,
            started_at=started.isoformat(),
            inputs=list(inputs),
        )
        self.write_manifest(run_dir, manifest)
        return manifest, run_dir

    def raw_dir(self, run_dir: Path, doc_id: str) -> Path:
        return run_dir / "raw" / doc_id

    def pages_dir(self, run_dir: Path, doc_id: str) -> Path:
        return run_dir / "pages" / doc_id

    def save_documents(
        self,
        run_dir: Path,
        extracted: ExtractedDocument,
        processed: ProcessedDocument,
    ) -> None:
        docs = run_dir / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / f"{extracted.doc_id}.extracted.json").write_text(
            extracted.model_dump_json(indent=2), encoding="utf-8"
        )
        (docs / f"{processed.doc_id}.processed.json").write_text(
            processed.model_dump_json(indent=2), encoding="utf-8"
        )
        (docs / f"{processed.doc_id}.md").write_text(
            processed.markdown, encoding="utf-8"
        )

    def save_llm_context(
        self,
        run_dir: Path,
        doc_id: str,
        chunks: list[ContextChunk],
    ) -> list[Path]:
        docs = run_dir / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        if len(chunks) == 1:
            dest = docs / f"{doc_id}.llm.md"
            dest.write_text(chunks[0].text, encoding="utf-8")
            written.append(dest)
            return written
        for i, chunk in enumerate(chunks, start=1):
            dest = docs / f"{doc_id}.llm.part{i:02d}.md"
            dest.write_text(chunk.text, encoding="utf-8")
            written.append(dest)
        return written

    def write_manifest(self, run_dir: Path, manifest: RunManifest) -> None:
        (run_dir / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
