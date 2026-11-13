from collections.abc import AsyncIterator

from fastapi import Request
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agent_log import LogConnect
from app.errors import ApiError


def create_pools(database_url: str) -> tuple[AsyncConnectionPool, AsyncConnectionPool]:
    """요청용(트랜잭션) 풀과 실행 로그용(autocommit) 풀을 만든다.

    로그를 따로 커밋해야 실패한 에이전트 실행도 agent_runs에 남는다.
    prepare_threshold=None: Supabase 트랜잭션 풀러(6543)에서도 동작하게 prepared statement를 끈다.
    check: 빌려주기 전에 연결이 살아 있는지 빈 문장 하나로 본다. 서버(풀러)가 끊은 연결은 버리고 새로 연다 —
    11/12 00:50 알림 발송이 끊긴 연결을 받아 실패했다. 빌릴 때마다 DB 왕복이 한 번 는다(같은 지역이라 몇 ms).
    """
    common = {"row_factory": dict_row, "prepare_threshold": None}
    check = AsyncConnectionPool.check_connection
    pool = AsyncConnectionPool(
        database_url, min_size=1, max_size=10, open=False, kwargs=common, check=check
    )
    log_pool = AsyncConnectionPool(
        database_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={**common, "autocommit": True},
        check=check,
    )
    return pool, log_pool


async def _connection(pool: AsyncConnectionPool | None) -> AsyncIterator[AsyncConnection]:
    if pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    async with pool.connection() as conn:  # 블록이 끝나면 커밋, 예외면 롤백
        yield conn


async def get_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    async for conn in _connection(request.app.state.pool):
        yield conn


def get_log_connect(request: Request) -> LogConnect:
    """agent_run()에 넘기는 autocommit 연결 공급자.

    연결 하나가 아니라 공급자를 준다. 로깅은 한 줄 쓸 때마다 빌렸다 돌려줘서, 모델을 기다리는
    오래 걸리는 실행이 로그 풀(max_size)을 붙잡지 않는다(app/agent_log.py).
    """
    log_pool = getattr(request.app.state, "log_pool", None)
    if log_pool is None:
        raise ApiError(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없어요.")
    return log_pool.connection
