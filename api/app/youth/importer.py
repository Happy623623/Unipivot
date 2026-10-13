"""온통청년 정책을 공고로 넣는다 (PRD F-11). 수집 한 번이 실행 하나(agent_runs.trigger_type = batch_crawl)다.

실행의 도구 호출은 둘이다. 넣은 공고의 extraction_run_id가 이 실행이라 공고 상세의 처리 과정에 그대로 보인다.
1. fetch_youth_policies: 온통청년에서 정책 목록을 끝까지 받는다(client.py)
2. build_youth_requirements: 가져올 정책을 고르고 요건을 만들어 저장한다(convert.py)

정책마다 한 트랜잭션이다.
- 새 정책·바뀐 정책(변환 결과의 content_hash가 다름): 공고 행을 넣거나 고치고 요건을 바꾼다(save_extraction).
  요건이 바뀌면 requirements_version이 오르고, 판정은 피드를 읽을 때 다시 계산된다.
- 같은 정책: 고치지 않는다. 조회수처럼 변환에 안 쓰는 칸만 바뀐 정책이다. 넣은 정책의 content_hash·상태를
  먼저 한 번에 읽어, 같고 활성인 정책은 DB에 다시 가지 않는다(원격 DB에서 정책마다 오가면 느리다).
- 가져온 정책이 숨김·만료였으면 활성으로 돌린다(만료는 마감이 지나지 않았을 때만). 상시 정책이 마감 코드로
  바뀌었다가 다시 상시가 되면 변환 결과가 전과 같아서, 같은 정책이어도 돌린다.
- 이미 넣은 정책이 범위를 벗어나면 마감·사업 종료는 만료, 수도권 밖·승인 안 됨은 숨김으로 바꾼다.
- 목록을 빠짐없이 받았을 때만 목록에서 사라진 정책을 숨긴다. 한 번에 활성 공고의 GONE_SHARE(최소 GONE_MIN건)
  넘게 사라졌으면 온통청년 목록이 덜 온 것일 수 있어 숨기지 않고 수만 남긴다(gone_kept). 온통청년에서 정말
  내려간 정책이면 hide_gone(명령의 --hide-gone)으로 숨긴다.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from psycopg import AsyncConnection

from app.agent_log import agent_run
from app.extraction.models import ExtractionResult
from app.extraction.store import save_extraction
from app.youth import BUILD_TOOL, FETCH_TOOL
from app.youth.client import BASE_URL, FetchResult, YouthPolicyClient
from app.youth.convert import PolicyRecord, Skip, convert
from app.youth.regions import region_table

SOURCE_TYPE = "youth_policy"
SOURCE_NAME = "온통청년"
SCOPE = "마감 전·상시, 전국+수도권"
GONE_MIN = 20
GONE_SHARE = 0.2

Saved = Literal["new", "updated", "unchanged"]


@dataclass
class CollectResult:
    run_id: str
    fetch: FetchResult
    counts: Counter[str] = field(default_factory=Counter)  # new·updated·unchanged·expired·hidden
    skips: Counter[str] = field(default_factory=Counter)  # 가져오지 않은 이유별 정책 수
    gone_kept: int = 0  # 목록에서 너무 많이 사라져 숨기지 않은 정책 수


async def ensure_source(conn: AsyncConnection) -> str:
    """sources의 온통청년 행. 없으면 만든다."""
    row = await (
        await conn.execute(
            "select id from sources where type = %s and base_url = %s order by id limit 1",
            (SOURCE_TYPE, BASE_URL),
        )
    ).fetchone()
    if row is None:
        row = await (
            await conn.execute(
                "insert into sources (type, name, base_url) values (%s, %s, %s) returning id",
                (SOURCE_TYPE, SOURCE_NAME, BASE_URL),
            )
        ).fetchone()
    return str(row["id"])


async def collect(
    conn: AsyncConnection,
    log_conn: AsyncConnection,
    client: YouthPolicyClient,
    *,
    today: date,
    scenario: str | None = None,
    hide_gone: bool = False,
) -> CollectResult:
    """conn은 데이터(autocommit, 정책마다 트랜잭션), log_conn은 실행 로그용이다. today는 KST 날짜다.
    온통청년 오류(YouthApiError)는 실행을 실패로 남기고 그대로 올라간다."""
    source_id = await ensure_source(conn)
    table = region_table()
    async with agent_run(log_conn, trigger="batch_crawl", scenario_code=scenario) as run:
        async with run.tool(FETCH_TOOL, {"page_size": 100, "scope": SCOPE}) as call:
            fetched = await client.fetch_all()
            call.output = fetched.summary()
        result = CollectResult(run_id=run.id, fetch=fetched)
        tool_input = {"policies": len(fetched.policies), "hide_gone": hide_gone}
        async with run.tool(BUILD_TOOL, tool_input) as call:
            known = await _known(conn, source_id)
            skipped: dict[str, Skip] = {}
            for policy in fetched.policies:
                converted = convert(policy, today, table)
                if isinstance(converted, Skip):
                    skipped[str(policy["plcyNo"])] = converted
                    result.skips[converted.reason] += 1
                elif known.get(converted.external_id) == (converted.content_hash, "active"):
                    result.counts["unchanged"] += 1  # 같고 활성인 공고는 DB에 다시 가지 않는다
                else:
                    result.counts[await save_policy(conn, source_id, converted, run.id)] += 1
            expired, hidden, result.gone_kept = await retire(
                conn,
                source_id,
                skipped,
                {str(policy["plcyNo"]) for policy in fetched.policies},
                known,
                complete=fetched.complete,
                hide_gone=hide_gone,
            )
            result.counts["expired"] += expired
            result.counts["hidden"] += hidden
            await conn.execute(
                "update sources set last_collected_at = now() where id = %s", (source_id,)
            )
            call.output = {
                "saved": dict(result.counts),
                "skipped": dict(result.skips),
                "gone_kept": result.gone_kept,
            }
    return result


async def _known(conn: AsyncConnection, source_id: str) -> dict[str, tuple[str | None, str]]:
    """이미 넣은 정책: 번호 → (content_hash, 상태). 정책마다 DB를 오가지 않게 한 번에 읽는다."""
    rows = await (
        await conn.execute(
            "select external_id, content_hash, status::text from opportunities"
            " where source_id = %s",
            (source_id,),
        )
    ).fetchall()
    return {row["external_id"]: (row["content_hash"], row["status"]) for row in rows}


async def save_policy(
    conn: AsyncConnection, source_id: str, record: PolicyRecord, run_id: str
) -> Saved:
    """정책 한 건을 한 트랜잭션으로 넣는다. 제목·기관·주소도 변환 결과(content_hash)에 들어 있다."""
    async with conn.transaction():
        existing = await (
            await conn.execute(
                "select id, content_hash from opportunities"
                " where source_id = %s and external_id = %s for update",
                (source_id, record.external_id),
            )
        ).fetchone()
        saved: Saved = "new" if existing is None else "updated"
        if existing is not None and existing["content_hash"] == record.content_hash:
            opportunity_id, saved = str(existing["id"]), "unchanged"
        else:
            opportunity_id = await _upsert(conn, source_id, record)
            await save_extraction(
                conn,
                opportunity_id,
                _as_extraction(record),
                run_id=run_id,
                content_hash=record.content_hash,
            )
        await conn.execute(_RESTORE, (opportunity_id,))
    return saved


async def _upsert(conn: AsyncConnection, source_id: str, record: PolicyRecord) -> str:
    row = await (
        await conn.execute(
            "insert into opportunities (source_id, source_type, external_id, category, title,"
            " organizer, original_url, raw_text) values (%(source_id)s, 'youth_policy',"
            " %(external_id)s, 'youth_policy', %(title)s, %(organizer)s, %(url)s,"
            " %(raw_text)s) on conflict (source_id, external_id) do update set"
            " title = excluded.title, organizer = excluded.organizer,"
            " original_url = excluded.original_url, raw_text = excluded.raw_text"
            " returning id",
            {
                "source_id": source_id,
                "external_id": record.external_id,
                "title": record.title,
                "organizer": record.organizer,
                "url": record.original_url,
                "raw_text": record.raw_text,
            },
        )
    ).fetchone()
    return str(row["id"])


async def retire(
    conn: AsyncConnection,
    source_id: str,
    skipped: dict[str, Skip],
    fetched: set[str],
    known: dict[str, tuple[str | None, str]],
    *,
    complete: bool,
    hide_gone: bool = False,
) -> tuple[int, int, int]:
    """범위를 벗어난 활성 공고를 만료·숨김으로 바꾼다. (만료 수, 숨김 수, 숨기지 않은 사라진 정책 수).

    known은 이번 수집 전에 읽은 넣은 정책(_known)이다. 목록에서 사라진 정책은 빠짐없이 받았을 때만 숨기고,
    한 번에 너무 많이 사라졌으면 hide_gone일 때만 숨긴다."""
    closed = [number for number, skip in skipped.items() if skip.expired]
    out = [number for number, skip in skipped.items() if not skip.expired]
    expired = (await conn.execute(_EXPIRE, (source_id, closed))).rowcount
    hidden = (await conn.execute(_HIDE, (source_id, out))).rowcount
    if not complete:
        return expired, hidden, 0
    active = {number for number, (_, status) in known.items() if status == "active"}
    gone = sorted(active - fetched)
    if not hide_gone and len(gone) > max(GONE_MIN, len(active) * GONE_SHARE):
        return expired, hidden, len(gone)
    hidden += (await conn.execute(_HIDE, (source_id, gone))).rowcount
    return expired, hidden, 0


_RESTORE = (
    "update opportunities set status = 'active' where id = %s and (status = 'hidden'"
    " or (status = 'expired' and (deadline_at is null or deadline_at > now())))"
)
_ACTIVE_OF_SOURCE = "where source_id = %s and status = 'active'"
_EXPIRE = (
    f"update opportunities set status = 'expired' {_ACTIVE_OF_SOURCE} and external_id = any(%s)"
)
_HIDE = f"update opportunities set status = 'hidden' {_ACTIVE_OF_SOURCE} and external_id = any(%s)"


def _as_extraction(record: PolicyRecord) -> ExtractionResult:
    """요건 저장(save_extraction)이 받는 모양. 코드로 만든 요건이라 신뢰도는 없다."""
    return ExtractionResult(
        succeeded=True,
        requirements=record.requirements,
        apply_start_at=record.apply_start_at,
        deadline_at=record.deadline_at,
        easy_summary=record.easy_summary,
        needs_review=bool(record.review_reasons),
        review_reasons=record.review_reasons,
    )
