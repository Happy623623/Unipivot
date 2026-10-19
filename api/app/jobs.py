"""정기 작업의 알맹이 (API 명세 12장). 두 곳에서 부른다.

- `POST /internal/jobs/*` — 사람이나 바깥 크론이 부를 때(`app/routers/internal.py`)
- 서버 안 스케줄러 — 켜 두면 알아서 도는 쪽(`app/scheduler.py`)

둘이 같은 함수를 부르게 둔 까닭은, 한쪽만 고쳐서 "손으로 부를 때와 저절로 돌 때가 다른" 일을
막으려는 것이다. 여기 함수들은 FastAPI를 모른다 — 다 만들어진 저장소·서비스와 `now`만 받는다.
"""

from datetime import date, datetime

from psycopg import AsyncConnection
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from app.agent_log import LogConnect
from app.errors import ApiError
from app.lms.sync import LmsSyncService
from app.push.send import PushSender
from app.repositories.notifications import NotificationRepository
from app.repositories.push import PushRepository
from app.schemas.lms import SyncJobResult
from app.schemas.notifications import ScheduleResult, SendResult
from app.schemas.youth import FetchPoliciesResult
from app.youth.client import YouthApiError, YouthPolicyClient
from app.youth.deps import ClientFactory
from app.youth.importer import collect

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


async def schedule_notifications(repo: NotificationRepository, *, now: datetime) -> ScheduleResult:
    """공고 알림(새 적격·마감 임박·정보 필요)을 예약한다.

    같은 알림은 한 번만 만들고(사용자당 `dedupe_key` 1행), 마감이 바뀌면 아직 보내지 않은 행의
    시각만 고친다. 보낼 이유가 없어진 행은 지운다(저장소 머리말).
    """
    return await repo.schedule(now=now)


async def send_notifications(
    repo: NotificationRepository,
    push_repo: PushRepository,
    sender: PushSender,
    *,
    now: datetime,
) -> SendResult:
    """보낼 때가 된 알림을 보낸다.

    숨긴 공고의 알림과 하루 한도를 넘는 알림은 보내지 않고 둔다. 푸시 구독이 없거나 푸시를 끈
    사용자는 푸시만 건너뛰고 알림함에는 남는다(F-35).

    푸시는 **알림함 행을 닫은 뒤에** 보낸다(F-33). 푸시가 실패해도 알림은 보낸 것으로 남는다 —
    같은 알림을 두 번 보내지 않는 쪽을 택했다(명세 10장). 사라진 구독(404·410)은 지운다.
    """
    sent = await repo.send(now=now)
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
