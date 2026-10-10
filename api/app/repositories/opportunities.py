"""공고 피드·상세와 판정 저장 (S1-5·S1-6, API 명세 v0.4 5장 · ERD v0.9 · 판정엔진_규칙.md 8장).

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
- 상세(S1-6)는 같은 잠금 아래에서 그 공고를 늘 다시 판정해 저장하고 조회 기록을 남긴다. 활성·마감
  공고는 공개 범위 안이면 보이고(피드의 include_expired와 같은 범위), 준비한 공고는 숨김·병합·수강
  종료가 되어도 본인에게 보인다. 그 밖(숨김·병합·과목 비공개·남의 포스터)은 보이지 않는다(404).

판정을 쓰거나 믿고 읽는 코드(공고 상세, 준비하기, 알림 배치)는 같은 규칙을 지킨다: profiles 행을
for no key update로 잠근 뒤 그 아래에서 읽은 프로필로 판정한다. 판정 행이 없을 수 있고(프로필 저장 뒤
지운 공고, 아직 판정 안 한 공고), 엔진 오류 행(조건 0개, ENGINE_ERROR_SUMMARY)이 있을 수 있다.
"""

import base64
import binascii
import hashlib
import json
import logging
import re
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
    Judgment,
    Profile,
    Requirement,
    check_eligibility,
    clause_rows,
    condition_rows,
    resolve_basis_date,
    to_kst_date,
)
from app.extraction.prompt import FETCH_ORIGINAL, READ_IMAGE, READ_TEXT, SUBMIT
from app.extraction.sources import whole
from app.schemas.opportunities import (
    CATEGORIES,
    ELIGIBILITY_STATUSES,
    SOURCE_TYPES,
    AttachmentItem,
    CalendarEventRef,
    Clause,
    Condition,
    DetailEligibility,
    DocumentItem,
    FeedCounts,
    FeedEligibility,
    OpportunityDetail,
    OpportunityItem,
    Prep,
    Process,
    ProcessStep,
)

logger = logging.getLogger(__name__)

NEW_DAYS = 7  # 새 공고: 등록 7일 이내이고 상세를 아직 열지 않음
SOON_DAYS = 3  # 마감 임박: D-3~D-day
UNJUDGED_SUMMARY = "원문 확인 필요: 자격 요건을 정리하지 못함"  # 요건 추출에 실패한 공고
ENGINE_ERROR_SUMMARY = "원문 확인 필요: 조건을 판정하지 못함"  # 판정 엔진이 오류를 낸 공고
# 처리 과정에서 모델이 고른 도구(요건 추출 에이전트). 그 밖의 단계는 정해진 순서(pipeline)다
_AGENT_TOOLS = frozenset({READ_TEXT, READ_IMAGE, FETCH_ORIGINAL, SUBMIT})
NOTE_MAX_CHARS = 200  # 처리 과정의 "고른 이유" 한 줄 길이
_LINK = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)  # 쉬운 설명(validate.py)과 같은 규칙
_PAGES = re.compile(r"(\d+)")  # Vision이 읽은 쪽 "4–6/8"의 첫 쪽

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
# 요건 행을 판정 엔진 입력 모양(JSON 배열)으로. 공고 행과 같은 문장에서 읽어야 요건과 요건 버전이
# 같은 시점의 값이다
_REQUIREMENTS_JSON = (
    "coalesce((select jsonb_agg(jsonb_build_object("
    "'id', r.id, 'clause_no', r.clause_no, 'field', r.field, 'operator', r.operator,"
    " 'value', r.value, 'basis', r.basis, 'is_ambiguous', r.is_ambiguous,"
    " 'evidence_text', r.evidence_text) order by r.clause_no, r.created_at, r.id)"
    " from requirements r where r.opportunity_id = o.id), '[]'::jsonb)"
)
_PREP_JOIN = " left join prep_plans p on p.user_id = %(uid)s and p.opportunity_id = o.id"
# 상세 한 건: 공고·요건·서류(내 준비 할 일)·첨부·처리 과정·캘린더를 한 문장으로 읽는다
_DETAIL = (
    "select o.id, o.title, o.organizer, o.category::text as category,"
    " o.source_type::text as source_type, o.status::text as status, o.original_url,"
    " o.easy_summary, o.apply_start_at, o.deadline_at, o.needs_review, o.extraction_confidence,"
    " o.eligibility_basis_date, o.requirements_version, o.extraction_run_id,"
    " coalesce(o.uploaded_by = %(uid)s, false) as uploaded_by_me,"
    # 과목 이름은 수강 중인지 따지지 않고 읽는다. 준비한 과목 공지는 수강을 끝낸 뒤에도 보인다
    " (select lc.name from lms_courses lc where lc.user_id = %(uid)s"
    " and lc.canvas_course_id = o.visible_canvas_course_id) as course_name,"
    " p.id as prep_plan_id, p.agent_run_id as prepare_run_id,"
    " exists(select 1 from opportunity_reports rp where rp.opportunity_id = o.id"
    " and rp.reporter_id = %(uid)s) as reported_by_me,"
    " " + _REQUIREMENTS_JSON + " as requirements,"
    " coalesce((select jsonb_agg(jsonb_build_object('id', d.id, 'name', d.name,"
    " 'issuer', d.issuer, 'how_to', d.how_to, 'lead_days', d.lead_days,"
    " 'effort_minutes', d.effort_minutes, 'form_url', d.form_url,"
    " 'is_required', coalesce(d.is_required, true), 'task_id', t.id, 'is_done', t.is_done)"
    " order by coalesce(d.is_required, true) desc, d.name, d.id)"
    " from opportunity_documents d left join planner_tasks t"
    " on t.prep_plan_id = p.id and t.document_id = d.id"
    " where d.opportunity_id = o.id), '[]'::jsonb) as documents,"
    " (select count(*) from planner_tasks t where t.prep_plan_id = p.id) as tasks_total,"
    " (select count(*) from planner_tasks t where t.prep_plan_id = p.id and t.is_done)"
    " as tasks_done,"
    " coalesce((select jsonb_agg(jsonb_build_object('id', ev.id, 'provider', ev.provider)"
    " order by ev.starts_at, ev.id) from calendar_events ev"
    " where ev.user_id = %(uid)s and ev.opportunity_id = o.id), '[]'::jsonb) as calendar_events,"
    " coalesce((select jsonb_agg(jsonb_build_object('id', a.id, 'seq', a.seq,"
    " 'file_name', a.file_name, 'source_url', a.source_url, 'method', a.extract_method,"
    " 'error', a.extract_error) order by a.seq, a.id)"
    " from opportunity_attachments a where a.opportunity_id = o.id), '[]'::jsonb) as attachments,"
    # 처리 과정은 추출 실행의 도구 호출이다. 고른 이유, 읽은 곳(첨부 번호, 실제로 읽기 시작한 위치.
    # 오류면 요청한 위치), 오류였는지, 제출을 받았는지만 꺼낸다. 읽은 글자는 꺼내지 않는다
    " coalesce((select jsonb_agg(jsonb_build_object('seq', s.seq, 'tool', s.tool_name,"
    " 'status', s.status, 'latency_ms', s.latency_ms, 'reason', s.input->>'reason',"
    " 'attachment_no', s.input->'attachment_no',"
    " 'offset', coalesce(s.output->'offset', s.input->'offset'),"
    " 'start_page', s.input->'start_page', 'pages', s.output->'pages',"
    " 'error', s.output->>'error' is not null, 'accepted', s.output->'accepted')"
    " order by s.seq, s.id)"
    " from tool_calls s where s.run_id = o.extraction_run_id), '[]'::jsonb) as steps"
    " from opportunities o"
    + _COURSE_JOIN
    + _PREP_JOIN
    # 준비한 공고는 상태와 상관없이 본인에게 보인다. 그 밖은 활성·마감 공고 중 공개 범위 안
    + " where o.id = %(oid)s and (p.id is not null or (o.status in ('active', 'expired') and"
    + _VISIBLE
    + "))"
)
# 조회 기록. 처음 연 시각은 그대로 두고 마지막 시각은 늦은 쪽을 남긴다. 시각을 고정한 실행(평가
# 러너·테스트)이 지난 시각으로 열어도 기록이 거꾸로 가지 않는다
_VIEW = (
    "insert into opportunity_views (user_id, opportunity_id, first_viewed_at, last_viewed_at)"
    " values (%s, %s, %s, %s) on conflict (user_id, opportunity_id) do update set"
    " last_viewed_at = greatest(opportunity_views.last_viewed_at, excluded.last_viewed_at)"
)


def _stale_sql(scope: str) -> str:
    """다시 판정할 공고와 그 요건."""
    return (
        "select o.id, o.requirements_version, o.eligibility_basis_date, o.deadline_at,"
        " e.user_id is not null as had_result, e.status::text as old_status,"
        " e.missing_fields as old_missing, " + _REQUIREMENTS_JSON + " as requirements"
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
        profile = Profile.from_row(await self._lock_profile(user_id, display_name))
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
                judged = _judge(item, profile, departments, today)
                payload.append(_payload(item, judged.stored))
                old = display_status(item["old_status"] or "", item["old_missing"] or ())
                if item["had_result"] and old != judged.label:
                    changed += 1
        await self._upsert(user_id, payload, now)
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

    async def detail(
        self,
        user_id: str,
        opportunity_id: str,
        *,
        now: datetime,
        display_name: str | None = None,
    ) -> OpportunityDetail | None:
        """공고 상세(S1-6). 이 사용자에게 보이지 않는 공고면 None이다.

        피드와 같은 잠금 아래에서 그 공고를 다시 판정해 저장하고, 조회 기록을 남긴다(is_new가 꺼진다).
        """
        profile_row = await self._lock_profile(user_id, display_name)
        row = await (
            await self.conn.execute(_DETAIL, {"uid": user_id, "oid": opportunity_id})
        ).fetchone()
        if row is None:
            return None
        if row["extraction_run_id"] is None:  # 요건 추출에 실패한 공고는 판정하지 않는다
            await self.conn.execute(
                "delete from eligibility_results where user_id = %s and opportunity_id = %s",
                (user_id, opportunity_id),
            )
            eligibility = DetailEligibility(
                status="undetermined",
                display_status="needs_review",
                reason_text=UNJUDGED_SUMMARY,
                basis_date=None,
                requirements_version=row["requirements_version"],
                missing_fields=[],
                clauses=[],
                conditions=[],
                evaluated_at=None,
            )
        else:
            profile = Profile.from_row(profile_row)
            departments = await self._departments()
            judged = _judge(row, profile, departments, now.astimezone(KST).date())
            await self._upsert(user_id, [_payload(row, judged.stored)], now)
            eligibility = _detail_eligibility(
                judged, profile, departments, row["requirements_version"], now
            )
        await self.conn.execute(_VIEW, (user_id, opportunity_id, now, now))
        names = {item["seq"]: item["file_name"] for item in row["attachments"]}
        apply_start: datetime | None = row["apply_start_at"]
        deadline: datetime | None = row["deadline_at"]
        confidence = row["extraction_confidence"]
        return OpportunityDetail(
            id=str(row["id"]),
            title=row["title"],
            organizer=row["organizer"],
            category=row["category"],
            source_type=row["source_type"],
            status=row["status"],
            original_url=row["original_url"],
            poster_url=None,  # TODO(W6): 포스터 업로드에서 Storage 서명 URL(5분)을 붙인다
            easy_summary=row["easy_summary"],
            apply_start_at=apply_start.astimezone(KST) if apply_start else None,
            deadline_at=deadline.astimezone(KST) if deadline else None,
            needs_review=bool(row["needs_review"]),
            extraction_confidence=float(confidence) if confidence is not None else None,
            uploaded_by_me=row["uploaded_by_me"],
            course_name=row["course_name"],
            attachments=[_attachment(item) for item in row["attachments"] if item["source_url"]],
            eligibility=eligibility,
            documents=[DocumentItem(**document) for document in row["documents"]],
            prep=Prep(
                prepared=row["prep_plan_id"] is not None,
                prep_plan_id=_text(row["prep_plan_id"]),
                tasks_total=row["tasks_total"],
                tasks_done=row["tasks_done"],
                calendar_events=[CalendarEventRef(**event) for event in row["calendar_events"]],
            ),
            process=Process(
                extraction=[_step(step, names) for step in row["steps"]],
                evaluated_at=eligibility.evaluated_at,
                prepare_run_id=_text(row["prepare_run_id"]),
            ),
            reported_by_me=row["reported_by_me"],
        )

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

    async def _lock_profile(self, user_id: str, display_name: str | None) -> dict[str, Any]:
        """프로필 행을 (없으면 만들고) 잠근 뒤 읽는다.

        같은 사용자의 판정은 한 번에 하나씩: 프로필 저장과 피드 읽기가 겹쳐도 옛 프로필로 덮어쓰지 않는다.
        no key update라서 이 사용자의 다른 행(이벤트·알림 등)이 profiles를 참조하며 넣는 것은 막지 않는다.
        """
        await self.conn.execute(
            "insert into profiles (id, display_name) values (%s, %s) on conflict do nothing",
            (user_id, display_name),
        )
        row = await (
            await self.conn.execute(
                "select * from profiles where id = %s for no key update", (user_id,)
            )
        ).fetchone()
        assert row is not None
        return row

    async def _upsert(self, user_id: str, payload: list[dict[str, Any]], now: datetime) -> None:
        """판정 여러 개를 한 문장으로 저장한다(_payload 모양)."""
        if payload:
            await self.conn.execute(
                _UPSERT,
                {"uid": user_id, "engine": ENGINE_VERSION, "now": now, "rows": Jsonb(payload)},
            )

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


@dataclass(frozen=True)
class _Judged:
    stored: dict[str, Any]  # eligibility_results에 넣을 값(Judgment.storage_row 모양)
    label: str  # display_status
    judgment: Judgment | None  # 엔진이 오류를 냈으면 None
    requirements: tuple[Requirement, ...]
    basis_date: date | None


def _judge(
    item: dict[str, Any], profile: Profile, departments: list[Department], today: date
) -> _Judged:
    """공고 행 하나(requirements·eligibility_basis_date·deadline_at)를 판정한다.

    엔진 오류면 "판정하지 못함" 행을 돌려준다: 그 공고만 원문 확인 필요로 보인다.
    """
    basis: date | None = None
    try:
        requirements = tuple(Requirement.from_row(r) for r in item["requirements"])
        basis = resolve_basis_date(item["eligibility_basis_date"], item["deadline_at"], today)
        judgment = check_eligibility(
            list(requirements), profile, basis_date=basis, departments=departments
        )
        return _Judged(
            judgment.storage_row(), judgment.display_status, judgment, requirements, basis
        )
    except Exception:
        logger.exception("판정하지 못한 공고: %s", item["id"])
        return _Judged(_engine_error_row(), "needs_review", None, (), basis)


def _engine_error_row() -> dict[str, Any]:
    """엔진이 오류를 낸 공고에 저장하는 판정: 조건 0개, 원문 확인 필요. 부를 때마다 새로 만든다."""
    return {
        "status": "undetermined",
        "condition_results": [],
        "missing_fields": [],
        "reason_text": ENGINE_ERROR_SUMMARY,
    }


def _payload(item: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    """_UPSERT의 jsonb_to_recordset 행 하나."""
    return {
        "opportunity_id": str(item["id"]),
        "status": stored["status"],
        "condition_results": stored["condition_results"],
        "missing_fields": stored["missing_fields"],
        "reason_text": stored["reason_text"],
        "requirements_version": item["requirements_version"],
    }


def _detail_eligibility(
    judged: _Judged,
    profile: Profile,
    departments: list[Department],
    requirements_version: int,
    now: datetime,
) -> DetailEligibility:
    """상세의 판정표. 조건 문구는 엔진(describe)이 만들고, 내 값은 저장한 값과 같은 모양이다."""
    judgment = judged.judgment
    if judgment is None:  # 엔진 오류: 판정표 없이 원문 확인 필요
        return DetailEligibility(
            status="undetermined",
            display_status="needs_review",
            reason_text=ENGINE_ERROR_SUMMARY,
            basis_date=judged.basis_date,
            requirements_version=requirements_version,
            missing_fields=[],
            clauses=[],
            conditions=[],
            evaluated_at=now.astimezone(KST),
        )
    by_id = {requirement.id: requirement for requirement in judged.requirements}
    user_values = {
        result["requirement_id"]: result["user_value"]
        for result in judged.stored["condition_results"]
    }
    conditions = [
        Condition(
            **row,
            operator=by_id[row["requirement_id"]].operator,
            value=by_id[row["requirement_id"]].value,
            user_value=user_values[row["requirement_id"]],
        )
        for row in condition_rows(judgment, judged.requirements, profile, departments)
    ]
    return DetailEligibility(
        status=judgment.status,
        display_status=judgment.display_status,
        reason_text=judgment.reason_text,
        basis_date=judgment.basis_date,
        requirements_version=requirements_version,
        missing_fields=list(judgment.missing_fields),
        clauses=[Clause(**clause) for clause in clause_rows(judgment)],
        conditions=conditions,
        evaluated_at=now.astimezone(KST),
    )


def _step(step: dict[str, Any], names: dict[int, str]) -> ProcessStep:
    """처리 과정 한 줄(_DETAIL의 steps 행 하나). 첨부를 읽은 단계는 첨부 이름을 넣어 보인다.

    도구가 오류를 돌려준 호출(없는 첨부 번호 등)과 거절된 제출은 실행 로그에 succeeded로 남는다
    (에이전트는 오류를 모델에 돌려주고 계속 간다). 화면에는 실패로 보인다. 첨부 번호·위치는
    에이전트와 같은 규칙(whole)으로 읽는다.
    """
    tool: str = step["tool"]
    again = "이어 " if _continued(step) else ""
    if tool in (READ_TEXT, READ_IMAGE):
        number = whole(step.get("attachment_no"))
        name = names.get(number) if number is not None else None
        target = f"첨부 '{name}'" if name else f"첨부 {number}번" if number else "첨부"
        how = "이미지로 " if tool == READ_IMAGE else ""
        label = f"{target} {how}{again}읽기"
    elif tool == FETCH_ORIGINAL:
        label = f"공고 원문 페이지 {again}읽기"
    else:
        label = "지원 자격 정리" if tool == SUBMIT else tool
    failed = step.get("error") is True or (tool == SUBMIT and step.get("accepted") is False)
    return ProcessStep(
        seq=step["seq"],
        tool=tool,
        label=label,
        status="failed" if failed else step["status"],
        latency_ms=step["latency_ms"],
        chosen_by="agent" if tool in _AGENT_TOOLS else "pipeline",
        note=_note(step.get("reason")),
    )


def _continued(step: dict[str, Any]) -> bool:
    """앞에서 읽은 곳의 뒷부분을 읽은 호출. 도구가 실제로 읽은 위치를 보고, 오류면 요청한 위치를 본다.

    글자 읽기·원문 읽기는 시작 위치(offset)가 0보다 크면, Vision은 PDF를 2쪽부터 읽었으면 이어 읽기다.
    이미지는 한 장이라 이어 읽기가 없다.
    """
    if step["tool"] != READ_IMAGE:
        offset = whole(step.get("offset"))
        return offset is not None and offset > 0
    pages = step.get("pages")  # 읽은 PDF 쪽 "4–6/8". 이미지는 없다
    if isinstance(pages, str) and (first := _PAGES.match(pages)):
        return int(first.group(1)) > 1
    if step.get("error") is not True:
        return False  # 이미지를 읽었다
    start_page = whole(step.get("start_page"))
    return start_page is not None and start_page > 1


def _note(reason: Any) -> str | None:
    """모델이 고른 이유를 화면용 한 줄로: 주소를 지우고 공백·줄바꿈을 한 칸으로 줄여 NOTE_MAX_CHARS자까지.

    이유는 공고 글을 읽은 모델이 쓴 글이라, 공고 속 지시문이 링크를 끼워 넣지 못하게 쉬운 설명과
    같은 규칙으로 정리한다(app/extraction/validate.py).
    """
    if not isinstance(reason, str):
        return None
    line = " ".join(_LINK.sub("", reason).split())
    if len(line) > NOTE_MAX_CHARS:
        line = line[: NOTE_MAX_CHARS - 1].rstrip() + "…"
    return line or None


def _attachment(item: dict[str, Any]) -> AttachmentItem:
    if item["error"]:
        status = "failed"
    elif item["method"]:
        status = "succeeded"
    else:
        status = "skipped"  # 에이전트가 읽지 않은 첨부
    return AttachmentItem(
        id=str(item["id"]),
        file_name=item["file_name"],
        source_url=item["source_url"],
        extract_status=status,
    )


def _text(value: Any) -> str | None:
    return str(value) if value is not None else None


def get_opportunity_repo(
    conn: Annotated[AsyncConnection, Depends(get_conn)],
) -> OpportunityRepository:
    return OpportunityRepository(conn)


OpportunityRepoDep = Annotated[OpportunityRepository, Depends(get_opportunity_repo)]
