"""공고 피드와 판정 저장 (S1-5, API 명세 v0.4 5장 · ERD v0.9 · 판정엔진_규칙.md 8장).

- 판정은 코드(app/eligibility)로 하고 eligibility_results에 남긴다. 피드를 읽을 때 그 목록에 나올
  공고의 낡은 판정만 다시 계산한다. 낡은 판정: 결과가 없음, 요건 버전이 다름(재추출), 엔진 버전이
  다름(판정 규칙·문구·오류 수정), 기준일이 "오늘"(기준일·마감일이 모두 없음)인데 판정한 날이 지남.
- 프로필 저장과 소득·수급 동의 철회는 같은 요청에서 그 사용자의 활성 공고를 모두 다시 판정하고(force),
  나머지 공고(마감·숨김·안 보임)의 판정은 지운다. 바뀌기 전 값(철회한 소득 값 포함)이 판정 기록에 남지
  않고, 지운 판정은 그 공고를 다시 보여 줄 때 새로 계산한다. 프로필을 바꾸는 코드를 새로 만들면 같은
  요청에서 refresh_judgments(force=True)를 부른다. 판정은 profiles.profile_updated_at을 보지 않는다.
- 시각은 요청이 넘긴 now 하나만 쓴다(판정 기준일, evaluated_at). 시각을 고정한 실행(평가 러너·테스트)도
  그 날짜로 판정한다(API 명세 v0.4 1장).
- 요건 추출에 실패한 공고(extraction_run_id null)는 판정하지 않는다. 피드에는 원문 확인 필요로 보인다.
  엔진이 오류를 낸 공고는 "판정하지 못함" 판정을 저장해 같은 오류를 요청마다 되풀이하지 않는다(하루에
  한 번, 그리고 프로필·요건·엔진 버전이 바뀌면 다시 시도한다).
- 요건을 추출했는데 판정이 없는 공고(이 요청이 판정한 뒤에 들어온 공고)는 이번 응답에서 뺀다.
- 공개 범위: 포스터는 올린 본인만, 과목 공지 공고는 수강 중인 과목만, 나머지는 로그인 사용자 모두.

판정을 쓰거나 믿고 읽는 코드(공고 상세, 준비하기, 알림 배치)는 같은 규칙을 지킨다: profiles 행을
for no key update로 잠근 뒤 그 아래에서 읽은 프로필로 판정한다. 판정 행이 없을 수 있고(프로필 저장 뒤
지운 공고, 아직 판정 안 한 공고), 엔진 오류 행(조건 0개, ENGINE_ERROR_SUMMARY)이 있을 수 있다.
"""

import base64
import binascii
import hashlib
import json
import logging
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import Depends
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.db import get_conn
from app.eligibility import (
    ENGINE_VERSION,
    KST,
    Department,
    Profile,
    Requirement,
    check_eligibility,
    resolve_basis_date,
    to_kst_date,
)
from app.schemas.opportunities import (
    CATEGORIES,
    ELIGIBILITY_STATUSES,
    SOURCE_TYPES,
    FeedCounts,
    FeedEligibility,
    OpportunityItem,
)

logger = logging.getLogger(__name__)

NEW_DAYS = 7  # 새 공고: 등록 7일 이내이고 상세를 아직 열지 않음
SOON_DAYS = 3  # 마감 임박: D-3~D-day
UNJUDGED_SUMMARY = "원문 확인 필요: 자격 요건을 정리하지 못함"  # 요건 추출에 실패한 공고
ENGINE_ERROR_SUMMARY = "원문 확인 필요: 조건을 판정하지 못함"  # 판정 엔진이 오류를 낸 공고

Sort = Literal["deadline", "recent"]

# 공개 범위(RLS opportunities_select_visible과 같은 규칙). 백엔드는 RLS를 받지 않아서 쿼리에 직접 건다
_COURSE_JOIN = (
    " left join lms_courses c on o.visible_canvas_course_id is not null"
    " and c.user_id = %(uid)s and c.canvas_course_id = o.visible_canvas_course_id and c.is_active"
)
_VISIBLE = (
    " (o.source_type <> 'poster' or o.uploaded_by = %(uid)s)"
    " and (o.visible_canvas_course_id is null or c.id is not null)"
)
_RESULT_JOIN = " left join eligibility_results e on e.user_id = %(uid)s and e.opportunity_id = o.id"
# 판정 결과를 쓰는 행: 요건 추출에 성공했고 결과가 있다. 요건 추출에 실패한 공고는 판정 불가로 보인다
_JUDGED = "(o.extraction_run_id is not null and e.user_id is not null)"
# 응답에 넣는 행. 요건을 추출했는데 판정이 없으면 이 요청이 판정한 뒤에 들어온 공고라 다음 요청에 보인다
_SHOWN = " (o.extraction_run_id is null or e.user_id is not null)"
_ACTIVE = " o.status = 'active' and (o.deadline_at is null or o.deadline_at >= %(now)s)"
_WITH_EXPIRED = " o.status in ('active', 'expired')"
# 값이 없는 행(마감일 없는 상시 공고, 등록 시각 없는 행)은 두 정렬 모두 맨 뒤다
_ORDER = {
    "deadline": "deadline_at asc nulls last, id asc",
    "recent": "created_at desc nulls last, id desc",
}
_UPSERT = (
    "insert into eligibility_results (user_id, opportunity_id, status, condition_results,"
    " missing_fields, reason_text, requirements_version, engine_version, evaluated_at)"
    " select %(uid)s::uuid, r.opportunity_id, r.status, r.condition_results, r.missing_fields,"
    " r.reason_text, r.requirements_version, %(engine)s, %(now)s"
    " from jsonb_to_recordset(%(rows)s) as r(opportunity_id uuid, status eligibility_status,"
    " condition_results jsonb, missing_fields text[], reason_text text, requirements_version int)"
    " on conflict (user_id, opportunity_id) do update set status = excluded.status,"
    " condition_results = excluded.condition_results, missing_fields = excluded.missing_fields,"
    " reason_text = excluded.reason_text, requirements_version = excluded.requirements_version,"
    " engine_version = excluded.engine_version, evaluated_at = excluded.evaluated_at"
)
_COUNTS = (
    "with base as (select o.created_at, o.deadline_at,"
    " case when " + _JUDGED + " then e.status::text else 'undetermined' end as status,"
    " case when " + _JUDGED + " then coalesce(cardinality(e.missing_fields), 0) else 0 end"
    " as missing,"
    " not exists(select 1 from opportunity_views v"
    " where v.user_id = %(uid)s and v.opportunity_id = o.id) as unseen"
    " from opportunities o"
    + _COURSE_JOIN
    + _RESULT_JOIN
    + " where"
    + _ACTIVE
    + " and"
    + _VISIBLE
    + " and"
    + _SHOWN
    + ")"
    " select count(*) filter (where status = 'eligible') as eligible,"
    " count(*) filter (where status = 'eligible' and created_at >= %(new_since)s and unseen)"
    " as new_eligible,"
    " count(*) filter (where status = 'undetermined') as undetermined,"
    " count(*) filter (where status = 'undetermined' and missing > 0) as missing_info,"
    " count(*) filter (where status = 'undetermined' and missing = 0) as needs_review,"
    " count(*) filter (where status = 'ineligible') as ineligible,"
    " count(*) filter (where status <> 'ineligible' and deadline_at is not null"
    " and (deadline_at at time zone 'Asia/Seoul')::date - %(today)s::date"
    " between 0 and %(soon)s) as deadline_soon"
    " from base"
)


def _stale_sql(scope: str) -> str:
    """다시 판정할 공고와 그 요건. 한 문장으로 읽어야 요건과 요건 버전이 같은 시점의 값이다."""
    return (
        "select o.id, o.requirements_version, o.eligibility_basis_date, o.deadline_at,"
        " e.user_id is not null as had_result, e.status::text as old_status,"
        " e.missing_fields as old_missing,"
        " coalesce((select jsonb_agg(jsonb_build_object("
        "   'id', r.id, 'clause_no', r.clause_no, 'field', r.field, 'operator', r.operator,"
        "   'value', r.value, 'basis', r.basis, 'is_ambiguous', r.is_ambiguous,"
        "   'evidence_text', r.evidence_text) order by r.clause_no, r.created_at, r.id)"
        "   from requirements r where r.opportunity_id = o.id), '[]'::jsonb) as requirements"
        " from opportunities o"
        + _COURSE_JOIN
        + _RESULT_JOIN
        + " where"
        + scope
        + " and"
        + _VISIBLE
        + " and o.extraction_run_id is not null"
        " and (%(force)s or e.user_id is null or e.evaluated_at is null"
        " or e.requirements_version <> o.requirements_version"
        " or e.engine_version <> %(engine)s"
        # 날이 바뀌면 다시: 기준일이 "오늘"인 공고, 엔진 오류로 판정하지 못한 공고(오류를 고쳤을 수 있다)
        " or (((o.eligibility_basis_date is null and o.deadline_at is null)"
        " or e.reason_text = %(engine_error)s)"
        " and (e.evaluated_at at time zone 'Asia/Seoul')::date < %(today)s))"
    )


def _feed_sql(where: str, outer: str, order: str) -> str:
    return (
        "with feed as (select o.id, o.title, o.organizer, o.category::text as category,"
        " o.source_type::text as source_type, o.deadline_at, o.created_at, o.easy_summary,"
        " o.needs_review, coalesce(o.uploaded_by = %(uid)s, false) as uploaded_by_me,"
        " c.name as course_name,"
        " exists(select 1 from prep_plans p where p.user_id = %(uid)s and p.opportunity_id = o.id)"
        " as prepared,"
        " coalesce(o.created_at >= %(new_since)s, false) and not exists(select 1"
        " from opportunity_views v where v.user_id = %(uid)s and v.opportunity_id = o.id) as is_new,"
        " " + _JUDGED + " as judged,"
        " case when " + _JUDGED + " then e.status::text else 'undetermined' end as eff_status,"
        " case when " + _JUDGED + " then coalesce(e.missing_fields, '{}') else '{}' end"
        " as eff_missing,"
        " e.reason_text"
        " from opportunities o" + _COURSE_JOIN + _RESULT_JOIN + " where" + where + ")"
        " select * from feed" + outer + " order by " + order + " limit %(limit)s"
    )


@dataclass(frozen=True)
class Cursor:
    scope: str  # 목록 조건(정렬·필터)의 지문. 조건이 다른 목록에는 쓸 수 없다
    # 마지막 행의 정렬 값(deadline: 마감 시각, recent: 등록 시각). 없을 수 있다
    value: datetime | None
    id: str


@dataclass(frozen=True)
class FeedQuery:
    eligibility: frozenset[str] | None = None  # None이면 전체
    categories: tuple[str, ...] | None = None
    source_types: tuple[str, ...] | None = None
    sort: Sort = "deadline"
    include_expired: bool = False
    limit: int = 20
    cursor: Cursor | None = None

    def scope(self) -> str:
        """cursor를 묶는 목록 조건의 지문. 정렬이나 필터를 바꾸면 목록을 처음부터 다시 부른다.

        같은 목록이면 지문도 같다: 값의 순서는 보지 않고, 모든 값을 고른 필터는 필터 없음과 같다.
        """
        parts = (
            self.sort,
            _filter_key(self.eligibility, ELIGIBILITY_STATUSES),
            _filter_key(self.categories, CATEGORIES),
            _filter_key(self.source_types, SOURCE_TYPES),
            str(self.include_expired),
        )
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _filter_key(values: Collection[str] | None, everything: Collection[str]) -> str:
    chosen = set(values or ())
    return "" if chosen >= set(everything) else ",".join(sorted(chosen))


@dataclass(frozen=True)
class FeedPage:
    items: list[OpportunityItem]
    next_cursor: str | None


@dataclass(frozen=True)
class Refresh:
    judged: int  # 다시 계산한 공고 수
    changed: int  # 라벨이 바뀐 공고 수(전에 판정이 있던 공고만 센다)


def display_status(status: str, missing_fields: Sequence[str]) -> str:
    """화면 라벨 4종. 판정 불가는 입력하면 바뀔 수 있으면 정보 필요, 아니면 원문 확인 필요다."""
    if status == "undetermined":
        return "missing_info" if missing_fields else "needs_review"
    return status


def encode_cursor(cursor: Cursor) -> str:
    data = {
        "q": cursor.scope,
        "v": cursor.value.isoformat() if cursor.value else None,
        "id": cursor.id,
    }
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(text: str) -> Cursor:
    """next_cursor로 준 값을 되돌린다. 모양이 틀리면 ValueError."""
    try:
        data = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
        scope, value, ident = data["q"], data["v"], data["id"]
        if not isinstance(scope, str) or not isinstance(ident, str):
            raise ValueError(scope)
        moment = None if value is None else datetime.fromisoformat(value)
        if moment is not None and moment.tzinfo is None:
            raise ValueError(value)
        return Cursor(scope=scope, value=moment, id=str(uuid.UUID(ident)))
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise ValueError("잘못된 cursor") from exc


class OpportunityRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def refresh_judgments(
        self,
        user_id: str,
        *,
        now: datetime,
        force: bool = False,
        include_expired: bool = False,
        display_name: str | None = None,
    ) -> Refresh:
        """피드에 나올 공고(include_expired면 지난 공고까지)의 낡은 판정을 다시 계산해 저장한다.

        force면 그 공고를 모두 다시 판정하고 나머지 공고의 판정은 지운다.
        프로필 행이 없으면(첫 요청이 피드) display_name과 함께 만든다.
        """
        await self.conn.execute(
            "insert into profiles (id, display_name) values (%s, %s) on conflict do nothing",
            (user_id, display_name),
        )
        # 같은 사용자의 판정은 한 번에 하나씩: 프로필 저장과 피드 읽기가 겹쳐도 옛 프로필로 덮어쓰지 않는다.
        # no key update라서 이 사용자의 다른 행(이벤트·알림 등)이 profiles를 참조하며 넣는 것은 막지 않는다
        row = await (
            await self.conn.execute(
                "select * from profiles where id = %s for no key update", (user_id,)
            )
        ).fetchone()
        assert row is not None
        profile = Profile.from_row(row)
        today = now.astimezone(KST).date()
        stale = await (
            await self.conn.execute(
                _stale_sql(_WITH_EXPIRED if include_expired else _ACTIVE),
                {
                    "uid": user_id,
                    "now": now,
                    "force": force,
                    "engine": ENGINE_VERSION,
                    "engine_error": ENGINE_ERROR_SUMMARY,
                    "today": today,
                },
            )
        ).fetchall()
        payload: list[dict[str, Any]] = []
        changed = 0
        if stale:
            departments = await self._departments()
            for item in stale:
                try:
                    requirements = [Requirement.from_row(r) for r in item["requirements"]]
                    basis = resolve_basis_date(
                        item["eligibility_basis_date"], item["deadline_at"], today
                    )
                    judgment = check_eligibility(
                        requirements, profile, basis_date=basis, departments=departments
                    )
                    stored = judgment.storage_row()
                    label = judgment.display_status
                except Exception:  # 엔진 오류: 이 공고만 "판정하지 못함"으로 남긴다(원문 확인 필요)
                    logger.exception("판정하지 못한 공고: %s", item["id"])
                    stored = {
                        "status": "undetermined",
                        "condition_results": [],
                        "missing_fields": [],
                        "reason_text": ENGINE_ERROR_SUMMARY,
                    }
                    label = "needs_review"
                payload.append(
                    {
                        "opportunity_id": str(item["id"]),
                        "status": stored["status"],
                        "condition_results": stored["condition_results"],
                        "missing_fields": stored["missing_fields"],
                        "reason_text": stored["reason_text"],
                        "requirements_version": item["requirements_version"],
                    }
                )
                old = display_status(item["old_status"] or "", item["old_missing"] or ())
                if item["had_result"] and old != label:
                    changed += 1
        if payload:
            await self.conn.execute(
                _UPSERT,
                {"uid": user_id, "engine": ENGINE_VERSION, "now": now, "rows": Jsonb(payload)},
            )
        if force:  # 다시 판정하지 않은 공고(마감·숨김·안 보임)의 판정은 지운다
            await self.conn.execute(
                "delete from eligibility_results"
                " where user_id = %s and opportunity_id <> all(%s::uuid[])",
                (user_id, [item["opportunity_id"] for item in payload]),
            )
        else:  # 요건 추출에 실패한 공고의 옛 판정은 지운다(판정하지 않는다)
            await self.conn.execute(
                "delete from eligibility_results e using opportunities o"
                " where e.user_id = %s and e.opportunity_id = o.id and o.extraction_run_id is null",
                (user_id,),
            )
        return Refresh(judged=len(payload), changed=changed)

    async def feed_page(self, user_id: str, query: FeedQuery, *, now: datetime) -> FeedPage:
        params: dict[str, Any] = {
            "uid": user_id,
            "now": now,
            "new_since": now - timedelta(days=NEW_DAYS),
            "limit": query.limit + 1,
        }
        where = [_WITH_EXPIRED if query.include_expired else _ACTIVE, _VISIBLE, _SHOWN]
        if query.categories:
            where.append(" o.category::text = any(%(categories)s)")
            params["categories"] = list(query.categories)
        if query.source_types:
            where.append(" o.source_type::text = any(%(source_types)s)")
            params["source_types"] = list(query.source_types)
        outer = []
        if query.eligibility:
            outer.append("eff_status = any(%(eligibility)s)")
            params["eligibility"] = sorted(query.eligibility)
        if query.cursor:
            outer.append(_after(query.sort, query.cursor))
            params["cursor_value"], params["cursor_id"] = query.cursor.value, query.cursor.id
        sql = _feed_sql(
            " and".join(where),
            " where " + " and ".join(outer) if outer else "",
            _ORDER[query.sort],
        )
        rows = await (await self.conn.execute(sql, params)).fetchall()
        today = now.astimezone(KST).date()
        page = rows[: query.limit]
        next_cursor = None
        if len(rows) > query.limit:
            last = page[-1]
            value = last["deadline_at"] if query.sort == "deadline" else last["created_at"]
            cursor = Cursor(scope=query.scope(), value=value, id=str(last["id"]))
            next_cursor = encode_cursor(cursor)
        return FeedPage(items=[_item(row, today) for row in page], next_cursor=next_cursor)

    async def feed_counts(self, user_id: str, *, now: datetime) -> FeedCounts:
        """홈 요약 카드: 필터와 상관없이 지금 보이는 활성 공고 전체 기준."""
        row = await (
            await self.conn.execute(
                _COUNTS,
                {
                    "uid": user_id,
                    "now": now,
                    "new_since": now - timedelta(days=NEW_DAYS),
                    "today": now.astimezone(KST).date(),
                    "soon": SOON_DAYS,
                },
            )
        ).fetchone()
        assert row is not None
        return FeedCounts.model_validate(row)

    async def _departments(self) -> list[Department]:
        """판정에 쓰는 학과 목록. 목록에서 빠진(폐지·통합) 학과도 단과대학·계열을 알아야 해서 모두 읽는다."""
        rows = await (
            await self.conn.execute("select name, college, field_group from departments")
        ).fetchall()
        return [Department.from_row(row) for row in rows]


def _after(sort: Sort, cursor: Cursor) -> str:
    """정렬 순서(_ORDER)에서 cursor 다음에 오는 행. 값이 없는 행은 맨 뒤에 id 순으로 온다."""
    column, beyond = ("deadline_at", ">") if sort == "deadline" else ("created_at", "<")
    if cursor.value is None:
        return f"({column} is null and id {beyond} %(cursor_id)s)"
    return (
        f"({column} {beyond} %(cursor_value)s"
        f" or ({column} = %(cursor_value)s and id {beyond} %(cursor_id)s) or {column} is null)"
    )


def _item(row: dict[str, Any], today: date) -> OpportunityItem:
    deadline: datetime | None = row["deadline_at"]
    status: str = row["eff_status"]
    missing = list(row["eff_missing"] or [])
    return OpportunityItem(
        id=str(row["id"]),
        title=row["title"],
        organizer=row["organizer"],
        category=row["category"],
        source_type=row["source_type"],
        deadline_at=deadline.astimezone(KST) if deadline else None,
        d_day=(to_kst_date(deadline) - today).days if deadline else None,
        easy_summary=row["easy_summary"],
        eligibility=FeedEligibility(
            status=status,
            display_status=display_status(status, missing),
            summary=(row["reason_text"] or "") if row["judged"] else UNJUDGED_SUMMARY,
            missing_fields=missing,
        ),
        needs_review=bool(row["needs_review"]),
        uploaded_by_me=row["uploaded_by_me"],
        course_name=row["course_name"],
        prepared=row["prepared"],
        is_new=row["is_new"],
    )


def get_opportunity_repo(
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> OpportunityRepository:
    return OpportunityRepository(conn)


OpportunityRepoDep = Annotated[OpportunityRepository, Depends(get_opportunity_repo)]
