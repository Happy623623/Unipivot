from collections.abc import Sequence
from dataclasses import replace
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.eligibility import KST
from app.errors import ApiError
from app.repositories.opportunities import FeedQuery, OpportunityRepoDep, decode_cursor
from app.schemas.opportunities import (
    CATEGORIES,
    ELIGIBILITY_STATUSES,
    SOURCE_TYPES,
    FeedResponse,
    MarkRequest,
    MarkResult,
    OpportunityDetail,
)

router = APIRouter(prefix="/opportunities", tags=["공고"])


def _values(
    field: str, raw: str | None, allowed: Sequence[str], errors: dict[str, str]
) -> tuple[str, ...] | None:
    """쉼표로 여러 값을 받는다. 비어 있으면 None(전체). 알 수 없는 값은 errors에 모은다."""
    values = tuple(dict.fromkeys(part.strip() for part in (raw or "").split(",") if part.strip()))
    if unknown := [value for value in values if value not in allowed]:
        errors[field] = f"알 수 없는 값: {', '.join(unknown)}"
    return values or None


@router.get("", response_model=FeedResponse)
async def read_feed(
    user: CurrentUserDep,
    repo: OpportunityRepoDep,
    now: NowDep,
    eligibility: Annotated[
        str | None,
        Query(
            description="eligible · undetermined · ineligible · all. 쉼표로 여러 개, 없으면 전체"
        ),
    ] = None,
    category: Annotated[
        str | None, Query(description="공고 카테고리(opportunity_category). 쉼표로 여러 개")
    ] = None,
    source_type: Annotated[
        str | None, Query(description="출처(source_type). 쉼표로 여러 개")
    ] = None,
    sort: Literal["deadline", "recent"] = "deadline",
    include_expired: bool = False,
    include_not_interested: Annotated[
        bool, Query(description="관심 없음으로 표시한 공고도 준다(F-45). 홈 숨김 탭용")
    ] = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[
        str | None, Query(description="앞 응답의 next_cursor. 정렬·필터가 같을 때만 쓴다")
    ] = None,
) -> FeedResponse:
    """추천 피드(F-40). 홈은 eligibility 없이 모두 받아 화면에서 지원 어려움 묶음과 탭으로 나눈다.

    읽기 전에 낡은 판정을 다시 계산한다. counts는 필터와 상관없이 활성 공고 전체 기준이고, 관심 없음
    공고는 세지 않는다. 관심 없음 공고는 include_not_interested일 때만 목록에 나온다.
    """
    errors: dict[str, str] = {}
    statuses = _values("eligibility", eligibility, (*ELIGIBILITY_STATUSES, "all"), errors)
    query = FeedQuery(
        eligibility=None if statuses is None or "all" in statuses else frozenset(statuses),
        categories=_values("category", category, CATEGORIES, errors),
        source_types=_values("source_type", source_type, SOURCE_TYPES, errors),
        sort=sort,
        include_expired=include_expired,
        include_not_interested=include_not_interested,
        limit=limit,
    )
    if cursor:
        try:
            decoded = decode_cursor(cursor)
        except ValueError:
            decoded = None
        if decoded is None or decoded.scope != query.scope():  # 망가졌거나 정렬·필터가 바뀜
            errors["cursor"] = "목록을 처음부터 다시 불러와 주세요."
        else:
            query = replace(query, cursor=decoded)
    if errors:
        raise ApiError(422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": errors})
    await repo.refresh_judgments(
        user.id, now=now, include_expired=include_expired, display_name=user.name
    )
    page = await repo.feed_page(user.id, query, now=now)
    counts = await repo.feed_counts(user.id, now=now)
    return FeedResponse(items=page.items, next_cursor=page.next_cursor, counts=counts)


@router.get("/{opportunity_id}", response_model=OpportunityDetail)
async def read_opportunity(
    opportunity_id: UUID, user: CurrentUserDep, repo: OpportunityRepoDep, now: NowDep
) -> OpportunityDetail:
    """공고 상세(S1-6). 그 자리에서 판정하고 조회 기록(opportunity_views)을 남긴다.

    공개 범위 안의 활성·마감 공고와 내가 준비한 공고(숨김·병합이 되어도)가 보인다.
    그 밖은 404 NOT_FOUND다.
    """
    detail = await repo.detail(user.id, str(opportunity_id), now=now, display_name=user.name)
    if detail is None:
        raise ApiError(404, "NOT_FOUND", "공고를 찾을 수 없어요.")
    return detail


@router.put("/{opportunity_id}/mark", response_model=MarkResult)
async def mark_opportunity(
    opportunity_id: UUID,
    body: MarkRequest,
    user: CurrentUserDep,
    repo: OpportunityRepoDep,
    now: NowDep,
) -> MarkResult:
    """관심·관심 없음 표시(F-45). 공고마다 하나이고 다른 표시를 보내면 바꾼다.

    상세를 열 수 있는 공고에만 붙인다. 그 밖은 404 NOT_FOUND다.
    """
    marked_at = await repo.set_mark(
        user.id, str(opportunity_id), body.mark, now=now, display_name=user.name
    )
    if marked_at is None:
        raise ApiError(404, "NOT_FOUND", "공고를 찾을 수 없어요.")
    return MarkResult(mark=body.mark, marked_at=marked_at.astimezone(KST))


@router.delete("/{opportunity_id}/mark", status_code=204, response_class=Response)
async def unmark_opportunity(
    opportunity_id: UUID, user: CurrentUserDep, repo: OpportunityRepoDep
) -> Response:
    """표시를 지운다(F-45). 표시가 없거나 보이지 않는 공고여도 204다(내 행만 지운다)."""
    await repo.clear_mark(user.id, str(opportunity_id))
    return Response(status_code=204)
