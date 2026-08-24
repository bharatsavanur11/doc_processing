from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from amr_preprocess.models import RawDocument

_EXT_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def sniff_mime(path: Path, data: bytes | None = None) -> str:
    ext = path.suffix.lower()
    if ext in _EXT_MIME:
        return _EXT_MIME[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    if data and data[:5] == b"%PDF-":
        return "application/pdf"
    if data and data[:2] == b"PK":
        return "application/zip"
    return "application/octet-stream"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def ingest_bytes(
    data: bytes,
    *,
    source_uri: str,
    filename: str,
    dest_dir: Path,
    parent_doc_id: str | None = None,
    mime_type: str | None = None,
) -> RawDocument:
    dest_dir.mkdir(parents=True, exist_ok=True)
    doc_id = content_hash(data)
    mime = mime_type or sniff_mime(Path(filename), data)
    dest = dest_dir / filename
    if dest.exists() and dest.stat().st_size != len(data):
        dest = dest_dir / f"{doc_id}_{filename}"
    dest.write_bytes(data)
    return RawDocument(
        doc_id=doc_id,
        source_uri=source_uri,
        mime_type=mime,
        filename=filename,
        bytes_path=str(dest),
        size_bytes=len(data),
        parent_doc_id=parent_doc_id,
        metadata={"sha256_16": doc_id},
    )


def ingest_path(
    path: Path,
    dest_dir: Path,
    parent_doc_id: str | None = None,
) -> RawDocument:
    path = path.expanduser().resolve()
    data = path.read_bytes()
    return ingest_bytes(
        data,
        source_uri=str(path),
        filename=path.name,
        dest_dir=dest_dir,
        parent_doc_id=parent_doc_id,
    )
