from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


PIPELINE_VERSION = "0.1.0"


class DocClass(str, Enum):
    REPORT = "report"
    DECK = "deck"
    SCANNED = "scanned"
    DOCX = "docx"
    PPTX = "pptx"
    SHEET = "sheet"
    EMAIL = "email"
    TEXT = "text"
    UNKNOWN = "unknown"


class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float
    page: Optional[int] = None


class TextBlock(BaseModel):
    block_id: str
    type: str = "paragraph"
    text: str
    page: Optional[int] = None
    bbox: Optional[BBox] = None


class ExtractedTable(BaseModel):
    table_id: str
    page: Optional[int] = None
    caption: Optional[str] = None
    headers: list[list[str]] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    extraction_method: str = "native"
    confidence: float = 0.0
    bbox: Optional[BBox] = None


class FigureAsset(BaseModel):
    figure_id: str
    page: Optional[int] = None
    bbox: Optional[BBox] = None
    image_path: Optional[str] = None
    caption: Optional[str] = None
    kind: str = "unknown"
    interpretation: Optional[dict[str, Any]] = None


class FigureLink(BaseModel):
    figure_id: str
    block_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class RawDocument(BaseModel):
    doc_id: str
    source_uri: str
    mime_type: str
    filename: str
    bytes_path: str
    size_bytes: int
    parent_doc_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Attachment(BaseModel):
    filename: str
    mime_type: str
    data: bytes
    parent_doc_id: str


class ExtractedDocument(BaseModel):
    doc_id: str
    parent_doc_id: Optional[str] = None
    source_uri: str
    filename: str
    doc_class: DocClass
    mime_type: str
    blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[ExtractedTable] = Field(default_factory=list)
    figures: list[FigureAsset] = Field(default_factory=list)
    figure_links: list[FigureLink] = Field(default_factory=list)
    page_count: int = 0
    page_image_paths: list[str] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list, exclude=True)


class ProcessedDocument(BaseModel):
    doc_id: str
    parent_doc_id: Optional[str] = None
    source_uri: str
    filename: str
    doc_class: DocClass
    mime_type: str
    markdown: str = ""
    blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[ExtractedTable] = Field(default_factory=list)
    figures: list[FigureAsset] = Field(default_factory=list)
    figure_links: list[FigureLink] = Field(default_factory=list)
    page_count: int = 0
    page_image_paths: list[str] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    pipeline_version: str = PIPELINE_VERSION


class RunManifest(BaseModel):
    run_id: str
    started_at: str
    finished_at: Optional[str] = None
    inputs: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    status: str = "running"
    pipeline_version: str = PIPELINE_VERSION
    warnings: list[str] = Field(default_factory=list)
    elapsed_ms: Optional[int] = None