"""공고 첨부 읽기. 순서: PDF 글자 → HWPX → HWP → (글자가 없으면) Vision. 정한 이유는 docs/요건추출_구현.md."""

from app.attachments.html import html_text
from app.attachments.reader import (
    KIND_LABELS,
    MIME_TYPES,
    AttachmentText,
    UnreadableAttachment,
    VisionPayload,
    clean_text,
    detect_format,
    read_attachment_text,
    vision_payload,
)

__all__ = [
    "KIND_LABELS",
    "MIME_TYPES",
    "AttachmentText",
    "UnreadableAttachment",
    "VisionPayload",
    "clean_text",
    "detect_format",
    "html_text",
    "read_attachment_text",
    "vision_payload",
]
