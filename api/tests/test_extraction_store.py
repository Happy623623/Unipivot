"""공고 변경 감지 해시(content_hash). 저장 자체는 test_extraction_db.py가 실제 스키마로 본다."""

from app.extraction import AttachmentInput
from app.extraction.store import content_hash


def test_content_hash_changes_with_body_or_files_only() -> None:
    one = AttachmentInput(1, "a.pdf", b"v1")
    base = content_hash("본문  내용\n", [one])
    assert base == content_hash("본문 내용", [AttachmentInput(1, "다른이름.pdf", b"v1")])
    assert base != content_hash("본문 내용 (수정)", [one])
    assert base != content_hash("본문 내용", [AttachmentInput(1, "a.pdf", b"v2")])
    two = AttachmentInput(2, "b.hwp", b"x")
    assert content_hash("t", [two, one]) == content_hash("t", [one, two])  # 첨부 순서(seq)로 센다
