"""정기 작업의 알맹이 (API 명세 12장). 두 곳에서 부른다.

- `POST /internal/jobs/*` — 사람이나 바깥 크론이 부를 때(`app/routers/internal.py`)
- 서버 안 스케줄러 — 켜 두면 알아서 도는 쪽(`app/scheduler.py`)

둘이 같은 함수를 부르게 둔 까닭은, 한쪽만 고쳐서 "손으로 부를 때와 저절로 돌 때가 다른" 일을
막으려는 것이다. 여기 함수들은 FastAPI를 모른다 — 다 만들어진 저장소·서비스와 `now`만 받는다.
"""

import logging
from datetime import date, datetime

from psycopg import AsyncConnection
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from app.agent_log import LogConnect
from app.errors import ApiError
from app.lms.sync import LmsSyncService
from app.push.send import PushSender
from app.repositories.notifications import NotificationRepository
from app.repositories.opportunities import OpportunityRepository
from app.repositories.push import PushRepository
from app.schemas.lms import SyncJobResult
from app.schemas.notifications import ScheduleResult, SendResult
from app.schemas.youth import FetchPoliciesResult
from app.youth.client import YouthApiError, YouthPolicyClient
from app.youth.deps import ClientFactory
from app.youth.importer import collect

logger = logging.getLogger(__name__)
CONNECT_TIMEOUT = 10  # 수집용 연결. psycopg 기본값(130초)은 막힌 네트워크에서 너무 오래 기다린다


async def lms_sync(service: LmsSyncService, *, now: datetime) -> SyncJobResult:
    """연결된 사용자의 과목·과제를 동기화한다 (F-51).

    한 사람이 실패해도 다음 사람을 계속한다(실패는 그 사람의 실행 기록에 남는다). 토큰이 막힌
    사람은 연결을 `error`로 바꿔 화면이 다시 연결을 안내한다. 최근에 동기화한 사람은 건너뛴다.
    """
    outcome = await service.sync_all(now=now)
    return SyncJobResult(
        users=outcome.users,
        synced=outcome.synced,
        failed=outcome.failed,
        skipped=outcome.skipped,
        new_assignments=outcome.new_assignments,
        due_changed=outcome.due_changed,
        submitted=outcome.submitted,
    )


async def schedule_notifications(
    repo: NotificationRepository, opportunities: OpportunityRepository, *, now: datetime
) -> ScheduleResult:
    """공고 알림(새 적격·마감 임박·정보 필요)을 예약한다.

    예약은 저장된 판정(`eligibility_results`)을 본다. 판정은 학생이 피드·상세를 열 때 계산되므로,
    예약하기 전에 공고 알림을 받을 사용자(동의를 마치고 공고 알림을 모두 끄지는 않은 사용자)마다 낡은
    판정(새 공고, 요건·엔진 버전이 바뀐 공고, 날이 바뀐 공고)을 다시 계산한다(PRD 6장 — 알림 작업이
    사용자마다 같은 판정 함수를 부른다). 그러지 않으면 공고가 들어온 뒤 앱을 열지 않은 학생에게는 새 공고
    알림이 가지 않고, 요건을 다시 추출한 공고는 옛 판정으로 알림이 나간다. 판정은 코드라 모델을 부르지 않는다.

    사용자마다 따로 확정한다. 한 트랜잭션에 모두 넣으면 작업이 끝날 때까지 사용자마다 프로필 행 잠금을
    쥐어 그 사용자의 피드·프로필 저장·탈퇴가 기다리고, 세이브포인트가 사용자 수만큼 쌓인다. 한 사용자의
    판정이 실패하면 그 사용자만 되돌리고 나머지와 예약은 계속한다. 연결이 끊기면 남은 사용자도 모두
    실패하므로 멈춘다. 목록을 읽은 뒤 그새 탈퇴한 사용자는 건너뛴다(프로필을 되살리지 않는다).

    부르는 쪽(요청·스케줄러)은 autocommit이 아닌 연결 하나를 두 저장소에 함께 준다. 목록을 읽은
    트랜잭션은 여기서 닫고(그래야 아래 블록이 세이브포인트가 아니라 사용자마다의 트랜잭션이 된다), 예약은
    부르는 쪽이 블록을 끝내며 확정한다.

    같은 알림은 한 번만 만들고(사용자당 `dedupe_key` 1행), 마감이 바뀌면 아직 보내지 않은 행의
    시각만 고친다. 보낼 이유가 없어진 행은 지운다(저장소 머리말).
    """
    conn = opportunities.conn
    users = await repo.alert_users()
    await conn.commit()
    judged = failed = 0
    for user_id in users:
        try:
            async with conn.transaction():
                refresh = await opportunities.refresh_judgments(
                    user_id, now=now, create_profile=False
                )
            judged += refresh.judged
        except Exception:
            if conn.closed:  # 연결이 끊겼다. 남은 사용자도 모두 실패한다
                raise
            failed += 1  # 그 사용자만 건너뛴다. 다음 예약 때 다시 본다
            logger.exception("알림 예약 전에 판정을 다시 계산하지 못했어요: user %s", user_id)
    logger.info(
        "알림 예약 전 판정: 사용자 %d명, 다시 계산한 판정 %d건, 실패 %d명",
        len(users),
        judged,
        failed,
    )
    return await repo.schedule(now=now)


async def send_notifications(
    repo: NotificationRepository,
    push_repo: PushRepository,
    sender: PushSender,
    *,
    now: datetime,
) -> SendResult:
    """보낼 때가 된 알림을 보낸다.

    숨긴 공고의 알림은 보내지 않고 두고, 하루 한도를 넘는 정보 필요 알림은 다음 날 09:00으로 미룬다.
    푸시 구독이 없거나 푸시를 끈 사용자는 푸시만 건너뛰고 알림함에는 남는다(F-35).

    푸시는 **알림함 행을 닫아 확정(커밋)한 뒤에** 보낸다(F-33). 푸시가 실패하거나 작업이 중간에 멈춰도
    알림은 보낸 것으로 남는다 — 같은 알림을 두 번 보내지 않는 쪽을 택했다(명세 10장). 발송이 둘 겹치면
    행을 먼저 닫은 쪽만 푸시한다(저장소 mark_sent). 사라진 구독(404·410)은 지운다.
    """
    sent = await repo.send(now=now)
    await repo.commit_sent()
    pushed = await sender.send(await push_repo.targets(sent.ids))
    dropped = await push_repo.drop_endpoints(pushed.gone)
    return SendResult(
        **{
            **sent.result.model_dump(),
            "pushed": pushed.sent,
            "push_failed": pushed.failed,
            "push_dropped": dropped,
        }
    )


async def fetch_policies(
    conn: AsyncConnection, log_connect: LogConnect, client: YouthPolicyClient, *, today: date
) -> FetchPoliciesResult:
    """온통청년 정책을 받아 공고로 넣는다 (F-11). 명령 `python -m app.youth.cli fetch`와 같은 일이다.

    `conn`은 **autocommit** 연결이어야 한다 — 정책마다 트랜잭션으로 묶어 넣고, 중간에 멈춰도 앞에서
    넣은 정책은 남긴다(요청 풀의 트랜잭션 연결은 맞지 않는다). 온통청년 오류는 502로 올린다.
    """
    try:
        result = await collect(conn, log_connect, client, today=today)
    except YouthApiError as exc:
        raise ApiError(502, "YOUTH_API_ERROR", str(exc)) from exc
    return FetchPoliciesResult(
        run_id=result.run_id,
        fetched=len(result.fetch.policies),
        total=result.fetch.total,
        complete=result.fetch.complete,
        stopped=result.fetch.stopped,
        new=result.counts["new"],
        updated=result.counts["updated"],
        unchanged=result.counts["unchanged"],
        expired=result.counts["expired"],
        hidden=result.counts["hidden"],
        skipped=sum(result.skips.values()),
        gone_kept=result.gone_kept,
    )


async def fetch_policies_fresh(
    *,
    database_url: str,
    api_key: str,
    log_connect: LogConnect,
    make_client: ClientFactory,
    today: date,
) -> FetchPoliciesResult:
    """연결과 클라이언트를 새로 열어 수집을 돌리고 닫는다. 라우터와 스케줄러가 함께 쓴다.

    키가 비었으면 온통청년을 부르기 전에 502로 끝낸다(`YOUTH_API_KEY`, api/.env).
    """
    if not api_key.strip():
        raise ApiError(502, "YOUTH_API_ERROR", "YOUTH_API_KEY가 비어 있어요(api/.env)")
    if not database_url:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    client = make_client(api_key)
    try:
        conn = await _autocommit_connection(database_url)
    except Exception as exc:
        await client.aclose()
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.") from exc
    try:
        return await fetch_policies(conn, log_connect, client, today=today)
    finally:
        await client.aclose()
        await conn.close()


async def _autocommit_connection(database_url: str) -> AsyncConnection:
    """수집용 autocommit 연결(app/crawl/cli.py의 `_connect`와 같은 꼴)."""
    timeout = None if "connect_timeout" in conninfo_to_dict(database_url) else CONNECT_TIMEOUT
    return await AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
        autocommit=True,
        prepare_threshold=None,
        connect_timeout=timeout,
    )
