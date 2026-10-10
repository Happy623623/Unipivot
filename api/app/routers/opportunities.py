from collections.abc import Sequence
from dataclasses import replace
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.errors import ApiError
from app.repositories.opportunities import FeedQuery, OpportunityRepoDep, decode_cursor
from app.schemas.opportunities import (
    CATEGORIES,
    ELIGIBILITY_STATUSES,
    SOURCE_TYPES,
    FeedResponse,
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
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[
        str | None, Query(description="앞 응답의 next_cursor. 정렬·필터가 같을 때만 쓴다")
    ] = None,
) -> FeedResponse:
    """추천 피드(F-40). 홈은 eligibility=eligible,undetermined로 부르고, 지원 어려움 묶음은 따로 부른다.

    읽기 전에 낡은 판정을 다시 계산한다. counts는 필터와 상관없이 활성 공고 전체 기준이다.
    """
    errors: dict[str, str] = {}
    statuses = _values("eligibility", eligibility, (*ELIGIBILITY_STATUSES, "all"), errors)
    query = FeedQuery(
        eligibility=None if statuses is None or "all" in statuses else frozenset(statuses),
        categories=_values("category", category, CATEGORIES, errors),
        source_types=_values("source_type", source_type, SOURCE_TYPES, errors),
        sort=sort,
        include_expired=include_expired,
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
