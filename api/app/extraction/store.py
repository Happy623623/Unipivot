"""추출 결과 저장 (ERD v0.9). 요건·서류 교체와 공고·첨부 갱신을 한 트랜잭션으로 한다.

- 성공: 요건·서류를 지우고 다시 넣는다. 마감일·신청 시작·기준일·쉬운 설명도 새로 뽑은 값으로 바꾼다
  (없으면 비운다. 바뀐 공고에서 옛 마감일이 남으면 판정 기준일과 알림이 틀린다).
- 실패(받은 제출 없음): 요건·서류를 지우고 extraction_run_id를 비운다. 내용이 바뀐 공고를 옛 요건으로
  계속 판정하지 않기 위해서다(판정엔진_규칙.md 8장: 추출에 실패한 공고는 판정하지 않는다).
  원문 확인 필요를 켜고, content_hash를 바꿔 같은 내용으로 다시 돌지 않게 한다.
  LLM 호출 오류로 실행 자체가 실패하면 이 함수를 부르지 않는다(다음 수집 때 다시 돈다).
- 전에 추출한 적이 있으면(extraction_run_id가 있었으면) requirements_version을 1 올린다.
  판정 결과의 버전이 공고와 다르면 낡은 결과다. 다시 판정은 호출하는 쪽이 한다.
- extraction_run_id는 지금 요건을 만든 실행이다. null이면 판정하지 않는다.
- 원문 확인 필요 이유(review_reasons)는 성공·실패 모두 이번 추출의 이유로 바꾼다(없으면 빈 배열).
  공고 상세가 그대로 보여 준다(F-42).
"""

import hashlib
from collections.abc import Iterable

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.eligibility import Department
from app.extraction.models import AttachmentInput, ExtractionResult


def content_hash(body: str, attachments: Iterable[AttachmentInput]) -> str:
    """공고가 바뀌었는지 보는 값: 본문 글자(공백 정리) + 첨부 파일 sha256(첨부 순서대로).

    첨부는 추출 글자가 아니라 파일 해시를 쓴다. 이미지·스캔본은 Vision 전에는 글자가 없고,
    해시를 내려고 첨부를 모두 읽으면 비용이 든다.
    """
    digest = hashlib.sha256(" ".join(body.split()).encode())
    for attachment in sorted(attachments, key=lambda item: item.seq):
        digest.update(b"\n" + hashlib.sha256(attachment.data).hexdigest().encode())
    return digest.hexdigest()


async def load_departments(conn: AsyncConnection) -> list[Department]:
    rows = await (
        await conn.execute(
            "select name, college, field_group from departments"
            " where is_active order by sort_order, name"
        )
    ).fetchall()
    return [Department.from_row(row) for row in rows]


async def save_extraction(
    conn: AsyncConnection,
    opportunity_id: str,
    result: ExtractionResult,
    *,
    run_id: str | None,
    content_hash: str,
) -> int:
    """저장하고 공고의 requirements_version을 돌려준다."""
    async with conn.transaction():
        row = await (
            await conn.execute(
                "select requirements_version, extraction_run_id from opportunities"
                " where id = %s for update",
                (opportunity_id,),
            )
        ).fetchone()
        if row is None:
            raise LookupError(f"공고가 없어요: {opportunity_id}")
        version: int = row["requirements_version"]
        if row["extraction_run_id"] is not None:
            version += 1  # 지금 요건이 바뀐다(새 요건이든, 실패로 비우든)
        await _replace_children(conn, opportunity_id, result)
        if result.succeeded:
            await conn.execute(
                "update opportunities set apply_start_at = %(apply_start_at)s,"
                " deadline_at = %(deadline_at)s, eligibility_basis_date = %(basis_date)s,"
                " easy_summary = %(summary)s, extraction_confidence = %(confidence)s,"
                " needs_review = %(needs_review)s, review_reasons = %(reasons)s,"
                " extraction_run_id = %(run_id)s, content_hash = %(hash)s,"
                " requirements_version = %(version)s where id = %(id)s",
                {
                    "apply_start_at": result.apply_start_at,
                    "deadline_at": result.deadline_at,
                    "basis_date": result.eligibility_basis_date,
                    "summary": result.easy_summary,
                    "confidence": result.confidence,
                    "needs_review": result.needs_review,
                    "reasons": list(result.review_reasons),
                    "run_id": run_id,
                    "hash": content_hash,
                    "version": version,
                    "id": opportunity_id,
                },
            )
        else:
            await conn.execute(
                "update opportunities set needs_review = true, review_reasons = %s,"
                " extraction_run_id = null, extraction_confidence = null, content_hash = %s,"
                " requirements_version = %s where id = %s",
                (list(result.review_reasons), content_hash, version, opportunity_id),
            )
        for attachment in result.attachments:
            if attachment.id is None or (attachment.method is None and attachment.error is None):
                continue  # 읽지 않은 첨부는 그대로 둔다(extract_method null)
            await conn.execute(
                "update opportunity_attachments set extracted_text = %s, extract_method = %s,"
                " extract_error = %s, extracted_at = now(), sha256 = coalesce(sha256, %s),"
                " mime_type = coalesce(mime_type, %s) where id = %s and opportunity_id = %s",
                (
                    attachment.text,
                    attachment.method,
                    attachment.error,
                    attachment.sha256,
                    attachment.mime_type,
                    attachment.id,
                    opportunity_id,
                ),
            )
    return version


async def _replace_children(
    conn: AsyncConnection, opportunity_id: str, result: ExtractionResult
) -> None:
    await conn.execute("delete from requirements where opportunity_id = %s", (opportunity_id,))
    # 요건은 clause_no, created_at 순으로 읽는다(판정, 상세 판정표). 한 트랜잭션의 now()는 모두 같아
    # 그대로 두면 묶음 안 순서가 id(무작위)로 정해진다. 1마이크로초씩 늘려 제출한 순서를 남긴다
    for index, requirement in enumerate(result.requirements):
        await conn.execute(
            "insert into requirements (opportunity_id, clause_no, field, operator, value, basis,"
            " evidence_text, is_ambiguous, created_at) values (%s, %s, %s, %s::req_operator, %s,"
            " %s, %s, %s, now() + %s * interval '1 microsecond')",
            (
                opportunity_id,
                requirement.clause_no,
                requirement.field,
                requirement.operator,
                Jsonb(requirement.value),
                requirement.basis,
                requirement.evidence_text,
                requirement.is_ambiguous,
                index,
            ),
        )
    await conn.execute(
        "delete from opportunity_documents where opportunity_id = %s", (opportunity_id,)
    )
    for document in result.documents:
        await conn.execute(
            "insert into opportunity_documents (opportunity_id, name, is_required, form_url)"
            " values (%s, %s, %s, %s)",
            (opportunity_id, document.name, document.is_required, document.form_url),
        )
