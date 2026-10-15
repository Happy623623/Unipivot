"""확인 화면에서 고친 값 받기 (F-16, API 명세 6장 POST /posters/confirm).

학생이 고칠 수 있는 것은 **기본 칸**이다: 제목·주최·종류·신청 기간·쉬운 설명. 요건과 서류는
**지운 것만** 반영한다(10/15 선택). 서버가 추출 초안을 기준으로 삼고, 학생이 보낸 목록에 남아
있는 줄만 남긴다.

요건의 항목(field)·연산자·값을 학생이 보낸 대로 저장하면, 화면에서 값을 지어내 판정 규칙을 넣을 수
있다. 지금은 포스터 공고가 올린 본인에게만 보이지만, 공유(P1)를 켜면 남의 판정까지 흔든다.
짝은 (묶음 번호, 항목, 연산자, 값)으로 맞춘다. 고쳐 보낸 줄은 짝이 없으니 지운 것으로 본다.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.errors import ApiError
from app.extraction.models import DocumentDraft, RequirementDraft
from app.schemas.posters import PosterDraft

MAX_TITLE = 200
MAX_ORGANIZER = 100
MAX_SUMMARY = 400


@dataclass(frozen=True)
class Confirmed:
    """저장할 값. 요건·서류는 초안에서 살아남은 줄이다."""

    title: str
    organizer: str | None
    category: str
    apply_start_at: datetime | None
    deadline_at: datetime | None
    easy_summary: str | None
    confidence: Decimal
    requirements: tuple[RequirementDraft, ...]
    documents: tuple[DocumentDraft, ...]


def confirm_draft(stored: PosterDraft, edited: PosterDraft, *, now: datetime) -> Confirmed:
    """추출 초안(stored)에 학생이 고친 기본 칸을 얹는다. 잘못된 입력은 422다.

    마감이 이미 지난 공고는 받지 않는다. 등록해도 판정이 생기지 않고(판정은 열린 공고만 한다)
    준비할 것도 없다.
    """
    # 종류(category)는 PosterDraft가 명세의 여덟 값만 받는다. 여기서 또 보지 않는다
    title = _one_line(edited.title, MAX_TITLE)
    if title is None:
        raise _invalid("title", "공고 이름을 적어 주세요.")
    deadline = edited.deadline_at
    if deadline is not None and deadline <= now:
        raise _invalid("deadline_at", "마감이 이미 지났어요. 날짜를 확인해 주세요.")
    apply_start = edited.apply_start_at
    if apply_start is not None and deadline is not None and apply_start > deadline:
        raise _invalid("apply_start_at", "신청 시작일이 마감일보다 늦어요.")
    kept_requirements = _kept(stored.requirements, edited.requirements, _requirement_key)
    kept_documents = _kept(stored.documents, edited.documents, _document_key)
    return Confirmed(
        title=title,
        organizer=_one_line(edited.organizer, MAX_ORGANIZER),
        category=edited.category,
        apply_start_at=apply_start,
        deadline_at=deadline,
        easy_summary=_one_line(edited.easy_summary, MAX_SUMMARY),
        # 신뢰도는 모델이 낸 값이다. 학생이 고칠 수 있는 칸이 아니다
        confidence=Decimal(str(stored.extraction_confidence)),
        requirements=tuple(
            RequirementDraft(
                clause_no=item.clause_no,
                field=item.field,
                operator=item.operator,
                value=item.value,
                basis=item.basis,  # 초안이 남긴 기준. 없으면 학과·지역 판정이 달라진다
                evidence_text=item.evidence_text,
                is_ambiguous=item.is_ambiguous,
            )
            for item in kept_requirements
        ),
        documents=tuple(
            DocumentDraft(name=item.name, is_required=True, form_url=item.form_url)
            for item in kept_documents
        ),
    )


def _kept[Item](
    stored: Sequence[Item], edited: Sequence[Item], key: Callable[[Item], str]
) -> list[Item]:
    """초안 순서를 지키면서, 학생이 보낸 목록에 남아 있는 줄만 남긴다.

    같은 줄이 여러 번 있을 수 있어 개수로 센다. 학생이 값을 고쳐 보낸 줄은 짝이 없어 빠진다.
    """
    wanted: dict[str, int] = {}
    for item in edited:
        wanted[key(item)] = wanted.get(key(item), 0) + 1
    kept: list[Item] = []
    for item in stored:
        found = key(item)
        if wanted.get(found, 0) > 0:
            wanted[found] -= 1
            kept.append(item)
    return kept


def _requirement_key(item: Any) -> str:
    return json.dumps(
        [item.clause_no, item.field, item.operator, item.value], sort_keys=True, ensure_ascii=False
    )


def _document_key(item: Any) -> str:
    return item.name.strip()


def _one_line(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.split())
    return cleaned[:limit] or None


def _invalid(field: str, reason: str) -> ApiError:
    return ApiError(
        422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": {field: reason}}
    )
