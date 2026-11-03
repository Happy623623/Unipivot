"""학교 공지 링크 가져오기 (B안, PRD F-10, API 명세 6장).

학생이 붙인 한양대 공지 주소 한 건을 그 자리에서 읽어 공고로 넣는다. 모델을 부르니 202와 run_id로 돌려주고
뒤에서 돈다(app/crawl/service.py). 가져온 공고는 학교 공지라 모든 학생에게 보인다.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.config import Settings, get_settings
from app.crawl.link import LinkError, parse_link
from app.crawl.service import DAILY_LINK_LIMIT, NO_MODEL, SEOUL, NoticeLinkServiceDep
from app.eligibility import KST
from app.errors import ApiError
from app.schemas.notices import NoticeLinkRequest, NoticeLinkStarted
from app.uploads import day_reset, day_start

router = APIRouter(prefix="/notices", tags=["학교 공지"])
DISABLED = "지금은 학교 공지 링크를 받지 않아요. 포스터로 올려 주세요."


def not_yet(opens: datetime) -> str:
    day = opens.astimezone(KST)
    return f"학교 공지 링크는 {day.month}월 {day.day}일부터 받아요. 그 전에는 포스터로 올려 주세요."


@router.post(
    "/link",
    response_model=NoticeLinkStarted,
    responses={202: {"model": NoticeLinkStarted, "description": "읽기 시작"}},
)
async def link_notice(
    body: NoticeLinkRequest,
    user: CurrentUserDep,
    service: NoticeLinkServiceDep,
    now: NowDep,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> NoticeLinkStarted:
    """공지 링크 한 건을 가져온다. 진행과 결과는 `GET /runs/{run_id}`로 본다.

    이미 가져온 공지면 학교 서버에 묻지 않고 200과 그 공고를 준다(`existing`). 같은 공지를 이미 읽고 있으면
    200과 그 실행을 준다. 새로 읽으면 202다. 하루 한도는 새로 읽는 것만 센다.
    `NOTICE_LINK_ENABLED`를 끄거나 여는 시각(`NOTICE_LINK_OPENS_AT`, 처리방침 v0.2 시행) 전이면 새로 읽지 않는다
    (409 NOTICE_LINK_DISABLED, 이미 가져온 공지는 그대로 준다). 모델 설정이 없는 서버는 502 LLM_ERROR다(실행을
    만들지 않는다). 같은 공지를 읽는 중인지와 하루 한도는 한 요청씩 보고 실행을 만든다(동시에 보내도 넘지 않는다).
    """
    try:
        link = parse_link(body.url)
    except LinkError as exc:
        raise ApiError(
            422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": {"url": exc.message}}
        ) from exc
    found = await service.existing(link.entry_id)
    if found is not None:
        if found.hidden:
            raise ApiError(422, "SEOUL_NOTICE", SEOUL)
        return NoticeLinkStarted(
            status="existing", run_id=None, opportunity_id=found.opportunity_id
        )
    if not settings.notice_link_enabled:
        raise ApiError(409, "NOTICE_LINK_DISABLED", DISABLED)
    opens = settings.notice_link_opens_at
    if opens is not None and now < opens:  # 이 기능을 적은 처리방침이 시행되기 전
        raise ApiError(409, "NOTICE_LINK_DISABLED", not_yet(opens))
    if not service.has_model():
        raise ApiError(502, "LLM_ERROR", NO_MODEL)
    async with service.admission():
        running = service.running(user.id, link.entry_id)
        if running is not None:
            return NoticeLinkStarted(status="running", run_id=running, opportunity_id=None)
        if await service.used_since(user.id, day_start(now)) >= DAILY_LINK_LIMIT:
            raise ApiError(
                429,
                "DAILY_LINK_LIMIT",
                f"오늘 가져올 수 있는 {DAILY_LINK_LIMIT}개를 다 썼어요. 내일 다시 붙여 주세요.",
                {"reset_at": day_reset(now).isoformat()},
            )
        run_id = await service.begin(user.id, link)
    response.status_code = 202
    response.headers["Location"] = f"{settings.api_prefix}/runs/{run_id}"
    return NoticeLinkStarted(status="running", run_id=run_id, opportunity_id=None)
