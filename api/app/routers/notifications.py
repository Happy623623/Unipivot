"""알림함 (F-35, API 명세 10장). 푸시를 못 받는 환경의 대체 수단이라 푸시와 상관없이 쌓인다."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.errors import ApiError
from app.repositories.notifications import LIST_LIMIT, NotificationRepoDep
from app.schemas.notifications import NotificationList, ReadRequest, ReadResult

router = APIRouter(prefix="/notifications", tags=["알림"])


@router.get("", response_model=NotificationList)
async def read_notifications(
    user: CurrentUserDep,
    repo: NotificationRepoDep,
    now: NowDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=LIST_LIMIT)] = 20,
    cursor: Annotated[str | None, Query(description="앞 응답의 next_cursor")] = None,
) -> NotificationList:
    """보낼 때가 지난 알림을 최신순으로. 안 읽은 수는 필터와 상관없이 전체 기준이다."""
    try:
        return await repo.listing(
            user.id, now=now, unread_only=unread_only, limit=limit, cursor=cursor
        )
    except ValueError:  # 망가진 cursor이거나 unread_only가 바뀐 목록의 cursor
        raise _invalid({"cursor": "알림함을 처음부터 다시 불러와 주세요."}) from None


@router.post("/read", response_model=ReadResult)
async def mark_read(
    body: ReadRequest, user: CurrentUserDep, repo: NotificationRepoDep, now: NowDep
) -> ReadResult:
    """고른 알림이나 전체를 읽음으로 바꾼다. 남의 알림과 아직 보낼 때가 안 된 알림은 바뀌지 않는다."""
    unread = await repo.read(user.id, now=now, ids=None if body.all else body.ids)
    return ReadResult(unread_count=unread)


def _invalid(fields: dict[str, str]) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": fields})
