from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path

from amr_preprocess.models import (
    Attachment,
    DocClass,
    ExtractedDocument,
    RawDocument,
    TextBlock,
)


def extract_eml(raw: RawDocument) -> ExtractedDocument:
    data = Path(raw.bytes_path).read_bytes()
    msg = BytesParser(policy=policy.default).parsebytes(data)
    return _from_message(raw, msg)


def extract_msg(raw: RawDocument) -> ExtractedDocument:
    try:
        import extract_msg
    except ImportError as exc:
        raise RuntimeError("extract-msg is required for .msg") from exc
    message = extract_msg.Message(raw.bytes_path)
    blocks = [
        TextBlock(
            block_id="subject",
            type="heading",
            text=message.subject or "",
            page=1,
        ),
        TextBlock(
            block_id="body",
            type="paragraph",
            text=(message.body or "")[:20000],
            page=1,
        ),
    ]
    attachments: list[Attachment] = []
    for att in message.attachments:
        name = att.longFilename or att.shortFilename or "attachment.bin"
        payload = att.data
        if payload:
            attachments.append(
                Attachment(
                    filename=name,
                    mime_type="application/octet-stream",
                    data=payload,
                    parent_doc_id=raw.doc_id,
                )
            )
    return ExtractedDocument(
        doc_id=raw.doc_id,
        parent_doc_id=raw.parent_doc_id,
        source_uri=raw.source_uri,
        filename=raw.filename,
        doc_class=DocClass.EMAIL,
        mime_type=raw.mime_type,
        blocks=[b for b in blocks if b.text.strip()],
        metadata={
            **raw.metadata,
            "from": str(message.sender or ""),
            "date": str(message.date or ""),
            "subject": str(message.subject or ""),
        },
        attachments=attachments,
        page_count=1,
    )


def _from_message(raw: RawDocument, msg) -> ExtractedDocument:
    subject = str(msg.get("subject") or "")
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        try:
            body = str(body_part.get_content())
        except Exception:
            body = ""
    blocks = []
    if subject:
        blocks.append(TextBlock(block_id="subject", type="heading", text=subject, page=1))
    if body.strip():
        blocks.append(TextBlock(block_id="body", type="paragraph", text=body[:20000], page=1))

    attachments: list[Attachment] = []
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment.bin"
        payload = part.get_content()
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        if not isinstance(payload, (bytes, bytearray)):
            continue
        attachments.append(
            Attachment(
                filename=name,
                mime_type=part.get_content_type() or "application/octet-stream",
                data=bytes(payload),
                parent_doc_id=raw.doc_id,
            )
        )

    return ExtractedDocument(
        doc_id=raw.doc_id,
        parent_doc_id=raw.parent_doc_id,
        source_uri=raw.source_uri,
        filename=raw.filename,
        doc_class=DocClass.EMAIL,
        mime_type=raw.mime_type,
        blocks=blocks,
        metadata={
            **raw.metadata,
            "from": str(msg.get("from") or ""),
            "to": str(msg.get("to") or ""),
            "date": str(msg.get("date") or ""),
            "subject": subject,
            "message_id": str(msg.get("message-id") or ""),
            "in_reply_to": str(msg.get("in-reply-to") or ""),
        },
        attachments=attachments,
        page_count=1,
    )
