"""포스터로 공고 등록 (F-16, API 명세 6장).

추출(POST /posters/extract)은 모델을 부르니 202와 run_id로 돌려주고 뒤에서 돈다. 등록
(POST /posters/confirm)은 모델을 부르지 않아 요청 트랜잭션 하나로 끝낸다 — 공고·요건·서류·판정이
함께 커밋되거나 함께 되돌아간다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.auth import CurrentUserDep
from app.clock import NowDep
from app.config import Settings, get_settings
from app.eligibility import KST
from app.errors import ApiError
from app.posters.confirm import confirm_draft
from app.posters.service import PosterServiceDep
from app.repositories.opportunities import OpportunityRepoDep
from app.repositories.posters import PosterRepoDep
from app.schemas.posters import (
    PosterConfirmRequest,
    PosterConfirmResult,
    PosterExtractRequest,
    PosterExtractStarted,
)

router = APIRouter(prefix="/posters", tags=["포스터"])


@router.post("/extract", status_code=202, response_model=PosterExtractStarted)
async def extract_poster(
    body: PosterExtractRequest,
    user: CurrentUserDep,
    service: PosterServiceDep,
    now: NowDep,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PosterExtractStarted:
    """올린 포스터에서 공고 초안을 뽑는다. 진행과 결과는 `GET /runs/{run_id}`로 본다."""
    file = await service.file(user.id, str(body.file_id))
    if file is None:
        raise ApiError(404, "NOT_FOUND", "올린 포스터를 찾을 수 없어요. 다시 올려 주세요.")
    run_id = await service.begin(user.id, file, now=now, today=now.astimezone(KST).date())
    response.headers["Location"] = f"{settings.api_prefix}/runs/{run_id}"
    return PosterExtractStarted(run_id=run_id, status="running")


@router.post("/confirm", status_code=201, response_model=PosterConfirmResult)
async def confirm_poster(
    body: PosterConfirmRequest,
    user: CurrentUserDep,
    repo: PosterRepoDep,
    opportunities: OpportunityRepoDep,
    now: NowDep,
    response: Response,
) -> PosterConfirmResult:
    """확인한 내용으로 공고를 만든다. 같은 공고가 이미 있으면 그 공고를 돌려준다(`merged`).

    요건·서류는 추출 초안을 기준으로 삼고 학생이 지운 줄만 뺀다(`app/posters/confirm.py`).
    만든 뒤 바로 업로더 본인 판정을 계산한다(다른 사용자 판정은 공유를 켤 때부터다).
    """
    stored = await repo.stored(user.id, str(body.run_id))
    if stored is None:
        raise ApiError(404, "NOT_FOUND", "읽어 온 포스터를 찾을 수 없어요. 다시 올려 주세요.")
    confirmed = confirm_draft(stored.draft, body.draft, now=now)
    duplicate = await repo.duplicate(
        user.id, title=confirmed.title, deadline_at=confirmed.deadline_at, now=now
    )
    if duplicate is not None:
        # 같은 공고를 또 만들지 않는다. 두 번 눌러도 공고는 하나다
        response.status_code = 200
        return PosterConfirmResult(opportunity_id=duplicate.opportunity_id, merged=True)
    opportunity_id = await repo.create(
        user.id, run_id=str(body.run_id), stored=stored, confirmed=confirmed
    )
    await opportunities.refresh_judgments(user.id, now=now, display_name=user.name)
    return PosterConfirmResult(opportunity_id=opportunity_id, merged=False)
