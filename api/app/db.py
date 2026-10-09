from collections.abc import AsyncIterator

from fastapi import Request
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.errors import ApiError


def create_pools(database_url: str) -> tuple[AsyncConnectionPool, AsyncConnectionPool]:
    """요청용(트랜잭션) 풀과 실행 로그용(autocommit) 풀을 만든다.

    로그를 따로 커밋해야 실패한 에이전트 실행도 agent_runs에 남는다.
    prepare_threshold=None: Supabase 트랜잭션 풀러(6543)에서도 동작하게 prepared statement를 끈다.
    """
    common = {"row_factory": dict_row, "prepare_threshold": None}
    pool = AsyncConnectionPool(database_url, min_size=1, max_size=10, open=False, kwargs=common)
    log_pool = AsyncConnectionPool(
        database_url, min_size=1, max_size=5, open=False, kwargs={**common, "autocommit": True}
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


async def get_log_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    """agent_run()에 넘기는 autocommit 연결."""
    async for conn in _connection(request.app.state.log_pool):
        yield conn
