"""내부·운영 API (API 명세 12장). 사용자 토큰이 아니라 서비스 키(`X-Internal-Key`)로만 부른다.

- `GET /internal/metrics` 기간별 성공률·응답시간·호출비용 + 판정 혼동행렬 + 제품 지표 5개(PRD 8장)
- `POST /internal/eval/run` 테스트 시나리오를 돌린다(CLI `python -m app.eval.cli`와 같은 함수)
- `POST /internal/jobs/lms-sync` LMS 연결된 사용자 동기화(30분마다)
- `POST /internal/jobs/schedule-notifications` 공고 알림 예약(하루 한 번)
- `POST /internal/jobs/send-notifications` 예약된 알림 발송(5분마다)

키가 틀렸을 때와 서버에 키가 없을 때 모두 403이다. 부른 쪽에 서버 설정 상태를 알려 주지 않는다.
키 값은 응답·로그에 남기지 않는다.
"""

import logging
import secrets
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query

from app import jobs
from app.clock import NowDep
from app.config import Settings, get_settings
from app.eligibility import KST
from app.errors import ApiError
from app.lms.sync import LmsSyncServiceDep
from app.push.deps import PushSenderDep
from app.repositories.metrics import MetricsRepoDep
from app.repositories.notifications import NotificationRepoDep
from app.repositories.push import PushRepoDep
from app.schemas.lms import SyncJobResult
from app.schemas.metrics import (
    EvalCheck,
    EvalRunRequest,
    EvalRunResult,
    EvalScenarioResult,
    Latency,
    Metrics,
)
from app.schemas.notifications import ScheduleResult, SendResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["내부"])

DEFAULT_DAYS = 30  # 기간을 주지 않으면 오늘까지 이만큼(KST)
FORBIDDEN = "이 API는 서비스 키로만 부를 수 있어요."


def internal_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_key: Annotated[str | None, Header()] = None,
) -> None:
    """서비스 키 검증. 같은 길이의 틀린 키로 시간을 재지 못하게 compare_digest로 본다."""
    expected = settings.internal_api_key
    if not expected:
        # 서버에 키가 없으면 아무도 부를 수 없다. 부른 쪽에는 그 사실을 알려 주지 않는다
        logger.warning("내부 API 키가 비어 있어요(INTERNAL_API_KEY). /internal/*는 모두 403이에요")
        raise ApiError(403, "FORBIDDEN", FORBIDDEN)
    if not x_internal_key or not secrets.compare_digest(x_internal_key, expected):
        raise ApiError(403, "FORBIDDEN", FORBIDDEN)


InternalKeyDep = Annotated[None, Depends(internal_key)]


@router.get("/metrics", response_model=Metrics)
async def read_metrics(
    repo: MetricsRepoDep,
    now: NowDep,
    _: InternalKeyDep,
    from_: Annotated[str | None, Query(alias="from", description="YYYY-MM-DD(KST)")] = None,
    to: Annotated[str | None, Query(description="YYYY-MM-DD(KST)")] = None,
) -> Metrics:
    """기간 지표. 기간을 주지 않으면 오늘까지 30일이다(KST 날짜, 양 끝 포함).

    판정 불가 비율만 기간이 아니라 지금 저장된 판정 기준이다(저장소 머리말).
    """
    today = now.astimezone(KST).date()
    end = _day(to, "to") if to else today
    start = _day(from_, "from") if from_ else end - timedelta(days=DEFAULT_DAYS - 1)
    if end < start:
        raise _invalid({"to": "끝 날짜는 시작 날짜보다 뒤여야 해요."})
    return await repo.metrics((start, end))


# 아래 세 작업의 알맹이는 `app/jobs.py`에 있다. 서버 안 스케줄러(app/scheduler.py)가 같은 함수를
# 부른다 — 손으로 부를 때와 저절로 돌 때가 달라지지 않게 한 곳에 뒀다.


@router.post("/jobs/lms-sync", response_model=SyncJobResult)
async def lms_sync(service: LmsSyncServiceDep, now: NowDep, _: InternalKeyDep) -> SyncJobResult:
    """연결된 사용자의 과목·과제를 동기화한다. 30분마다 도는 작업이다(F-51)."""
    return await jobs.lms_sync(service, now=now)


@router.post("/jobs/schedule-notifications", response_model=ScheduleResult)
async def schedule_notifications(
    repo: NotificationRepoDep, now: NowDep, _: InternalKeyDep
) -> ScheduleResult:
    """공고 알림(새 적격·마감 임박·정보 필요)을 예약한다. 하루 한 번 도는 작업이다."""
    return await jobs.schedule_notifications(repo, now=now)


@router.post("/jobs/send-notifications", response_model=SendResult)
async def send_notifications(
    repo: NotificationRepoDep,
    push_repo: PushRepoDep,
    sender: PushSenderDep,
    now: NowDep,
    _: InternalKeyDep,
) -> SendResult:
    """보낼 때가 된 알림을 보낸다(알림함 → 푸시). 5분마다 도는 작업이다."""
    return await jobs.send_notifications(repo, push_repo, sender, now=now)


@router.post("/eval/run", response_model=EvalRunResult)
async def run_eval(
    body: EvalRunRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    _: InternalKeyDep,
) -> EvalRunResult:
    """테스트 시나리오를 돌린다(PRD 8장). 돌린 기록은 `agent_runs`에 남고 지표 집계가 읽는다.

    DB 연결을 쥐지 않는다(저장소 의존이 없다). 시나리오는 자기 연결·풀을 따로 열고, 끝나면 만든
    사용자·공고를 지운다. 그래서 **시험용 DB**에서만 돌 수 있다.
    """
    # app.eval은 앱을 만들어 쓰므로(app.main) 모듈 맨 위에서 가져오면 순환 import가 된다
    from app.eval import pick, run_scenarios
    from app.eval.world import DEFAULT_NOW

    try:
        scenarios = pick(body.scenario_codes)
    except KeyError as exc:
        raise _invalid({"scenario_codes": str(exc).strip("'")}) from exc
    if not settings.database_url:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    try:
        report = await run_scenarios(settings.database_url, scenarios, now=body.now or DEFAULT_NOW)
    except RuntimeError as exc:  # 실제 Supabase DB면 돌리지 않는다(app/eval/world.py)
        logger.warning("시나리오를 돌리지 않았어요: %s", exc)
        raise ApiError(
            409, "EVAL_NOT_ALLOWED", "시나리오는 시험용 DB에서만 돌릴 수 있어요."
        ) from exc
    return EvalRunResult(
        now=report.now,
        priced_on=report.priced_on,
        scenarios=report.total,
        passed=report.passed,
        success_rate=report.success_rate,
        latency=Latency(p50_ms=report.p50, p95_ms=report.p95),
        cost_usd=float(report.cost_usd),
        llm_calls=report.llm_calls,
        results=[
            EvalScenarioResult(
                code=result.code,
                title=result.title,
                ok=result.ok,
                latency_ms=result.latency_ms,
                api_ms=result.api_ms,
                run_id=result.run_id,
                cost_usd=float(result.cost_usd),
                llm_calls=result.llm_calls,
                checks=[
                    EvalCheck(
                        what=check.what,
                        expected=check.expected,
                        actual=check.actual,
                        ok=check.ok,
                        kind=check.kind,
                    )
                    for check in result.checks
                ],
                error=result.error,
            )
            for result in report.results
        ],
    )


def _day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _invalid({field: "날짜를 YYYY-MM-DD로 적어 주세요."}) from None


def _invalid(fields: dict[str, str]) -> ApiError:
    return ApiError(422, "VALIDATION_FAILED", "입력값을 확인해 주세요.", {"fields": fields})
