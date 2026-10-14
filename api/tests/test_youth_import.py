"""온통청년 정책 넣기를 실제 스키마에 대고 확인한다: 새 정책 → 그대로 → 바뀐 정책, 범위를 벗어난 정책의
만료·숨김과 되돌리기, 빠짐없이 받지 못했을 때, 피드 판정과 상세의 처리 과정. DATABASE_URL이 있을 때만 돈다.

공고·출처 행은 트랜잭션을 되돌려 지우고, 실행 로그는 이 파일만 쓰는 scenario_code로 골라 지운다."""

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest

from app.agent_log import using
from app.eligibility import KST
from app.repositories.opportunities import FeedQuery, OpportunityRepository
from app.youth import BUILD_TOOL, FETCH_TOOL, importer
from app.youth.importer import CollectResult, collect
from tests.db_world import connect, make_user
from tests.youth_samples import FakeClient, policy, skip_if_other_youth_policies

DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]
TODAY = date(2026, 10, 13)
NOW = datetime(2026, 10, 13, 3, 0, tzinfo=UTC)
SCENARIO = f"test-{uuid.uuid4().hex[:12]}"
PREFIX = f"T{uuid.uuid4().hex[:8]}-"  # 정책 번호. 다른 테스트의 공고와 겹치지 않게


def item(name: str, **values: Any) -> dict[str, Any]:
    return policy(plcyNo=PREFIX + name, plcyNm=f"청년정책 {name}", **values)


ANSAN = {
    "zipCd": "41271,41273",
    "sprtTrgtMinAge": "19",
    "sprtTrgtMaxAge": "34",
    "aplyPrdSeCd": "0057001",
    "aplyYmd": "20261001 ~ 20261130",
}


async def run(
    conn: psycopg.AsyncConnection,
    log_conn: psycopg.AsyncConnection,
    *items: dict[str, Any],
    today: date = TODAY,
    **kw: Any,
) -> CollectResult:
    return await collect(
        conn, using(log_conn), FakeClient(list(items), **kw), today=today, scenario=SCENARIO
    )


async def rows(conn: psycopg.AsyncConnection) -> dict[str, dict[str, Any]]:
    found = await (
        await conn.execute(
            "select id, external_id, source_type::text, category::text, status::text, title,"
            " organizer, original_url, deadline_at, requirements_version, extraction_run_id,"
            " needs_review from opportunities where external_id like %s"
            " and source_type = 'youth_policy'",
            (PREFIX + "%",),
        )
    ).fetchall()
    return {row["external_id"].removeprefix(PREFIX): row for row in found}


async def school_notice(conn: psycopg.AsyncConnection, external_id: str) -> Any:
    """다른 출처(학교 공지)의 활성 공고. 번호가 정책과 같아도 온통청년 수집이 건드리지 않아야 한다."""
    source = await (
        await conn.execute(
            "insert into sources (type, name, base_url) values ('school_notice', '시험 공지', %s)"
            " returning id",
            (f"https://notice.example/{PREFIX}",),
        )
    ).fetchone()
    row = await (
        await conn.execute(
            "insert into opportunities (source_id, source_type, external_id, category, title)"
            " values (%s, 'school_notice', %s, 'scholarship', '학교 장학 공지') returning id",
            (source["id"], external_id),
        )
    ).fetchone()
    return row["id"]


async def status_of(conn: psycopg.AsyncConnection, opportunity_id: Any) -> str:
    row = await (
        await conn.execute(
            "select status::text from opportunities where id = %s", (opportunity_id,)
        )
    ).fetchone()
    return row["status"]


async def requirements(conn: psycopg.AsyncConnection, opportunity_id: Any) -> list[tuple]:
    found = await (
        await conn.execute(
            "select clause_no, field, operator::text, value, basis from requirements"
            " where opportunity_id = %s order by clause_no, created_at",
            (opportunity_id,),
        )
    ).fetchall()
    return [tuple(row.values()) for row in found]


async def cleanup(conn: psycopg.AsyncConnection, log_conn: psycopg.AsyncConnection) -> None:
    await conn.rollback()
    await conn.close()
    await log_conn.execute("delete from agent_runs where scenario_code = %s", (SCENARIO,))
    await log_conn.close()


async def test_new_unchanged_updated(monkeypatch: pytest.MonkeyPatch) -> None:
    saves: list[str] = []  # 정책 한 건 저장(트랜잭션)을 부른 정책
    save_policy = importer.save_policy

    async def counted(*args: Any) -> Any:
        saves.append(args[2].external_id.removeprefix(PREFIX))
        return await save_policy(*args)

    monkeypatch.setattr(importer, "save_policy", counted)
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)
        first = await run(
            conn,
            log_conn,
            item("A"),
            item("B", **ANSAN),
            item("C", aplyPrdSeCd="0057003"),
            item("D", zipCd="26110"),
        )
        assert (first.counts["new"], dict(first.skips)) == (2, {"마감": 1, "수도권 밖": 1})
        saved = await rows(conn)
        assert set(saved) == {"A", "B"}
        b = saved["B"]
        assert (b["source_type"], b["category"], b["status"]) == ("youth_policy",) * 2 + ("active",)
        assert (b["organizer"], b["requirements_version"]) == ("조달청", 1)
        assert str(b["extraction_run_id"]) == first.run_id
        assert b["deadline_at"].astimezone(KST) == datetime(2026, 11, 30, 23, 59, tzinfo=KST)
        assert b["original_url"].endswith(PREFIX + "B")
        assert await requirements(conn, b["id"]) == [
            (1, "age", "between", {"min": 19, "max": 34}, None),
            (2, "region", "in", ["경기도 안산시"], "unspecified"),
        ]
        assert await requirements(conn, saved["A"]["id"]) == []
        calls = await (
            await log_conn.execute(
                "select tool_name, status::text, output from tool_calls where run_id = %s"
                " order by seq",
                (first.run_id,),
            )
        ).fetchall()
        assert [(c["tool_name"], c["status"]) for c in calls] == [
            (FETCH_TOOL, "succeeded"),
            (BUILD_TOOL, "succeeded"),
        ]
        assert calls[0]["output"]["fetched"] == 4 and calls[0]["output"]["complete"] is True
        assert calls[1]["output"]["saved"] == {"new": 2, "expired": 0, "hidden": 0}
        trigger = await (
            await log_conn.execute(
                "select trigger_type::text, status::text from agent_runs where id = %s",
                (first.run_id,),
            )
        ).fetchone()
        assert trigger == {"trigger_type": "batch_crawl", "status": "succeeded"}

        assert saves == ["A", "B"]
        again = await run(conn, log_conn, item("A"), item("B", **ANSAN))
        assert again.counts["unchanged"] == 2 and again.counts["new"] == 0
        assert (await rows(conn))["B"]["requirements_version"] == 1
        assert saves == ["A", "B"]  # 같고 활성인 정책은 DB에 다시 가지 않는다

        changed = await run(
            conn, log_conn, item("A"), item("B", **{**ANSAN, "sprtTrgtMaxAge": "39"})
        )
        assert (changed.counts["updated"], changed.counts["unchanged"]) == (1, 1)
        assert saves == ["A", "B", "B"]
        after = await rows(conn)
        assert after["B"]["requirements_version"] == 2
        assert str(after["B"]["extraction_run_id"]) == changed.run_id
        assert str(after["A"]["extraction_run_id"]) == first.run_id  # 그대로인 정책은 둔다
        assert (await requirements(conn, after["B"]["id"]))[0][3] == {"min": 19, "max": 39}
    finally:
        await cleanup(conn, log_conn)


async def test_a_changed_policy_keeps_the_documents_prepare_made() -> None:
    """바뀐 정책을 다시 받아도 준비하기가 만든 서류와 학생 할 일이 남는다.

    청년정책은 수집이 서류를 주지 않는다(제출 서류는 글이라 준비하기가 읽어서 넣는다). 다시 받을 때
    서류를 지웠다 넣으면 이미 준비한 학생의 서류 목록이 비고 할 일 연결이 끊긴다.
    """
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)
        await run(conn, log_conn, item("B", **ANSAN))
        policy_id = (await rows(conn))["B"]["id"]
        user_id = await make_user(conn, grade=3)
        # 준비하기가 '제출 서류' 글에서 만들어 넣고 안내까지 채운 서류 둘
        document = await (
            await conn.execute(
                "insert into opportunity_documents (opportunity_id, name, issuer, how_to,"
                " lead_days) values (%s, '주민등록등본', '정부24', '정부24에서 발급', 0)"
                " returning id",
                (policy_id,),
            )
        ).fetchone()
        await conn.execute(  # 할 일이 걸리지 않은 서류도 남아야 한다(다시 묻지 않게)
            "insert into opportunity_documents (opportunity_id, name, issuer, lead_days)"
            " values (%s, '신청서', '신청 사이트', 0)",
            (policy_id,),
        )
        plan = await (
            await conn.execute(
                "insert into prep_plans (user_id, opportunity_id) values (%s, %s) returning id",
                (user_id, policy_id),
            )
        ).fetchone()
        await conn.execute(
            "insert into planner_tasks (user_id, prep_plan_id, document_id, title, due_date,"
            " source) values (%s, %s, %s, '주민등록등본 준비', current_date, 'prep_plan')",
            (user_id, plan["id"], document["id"]),
        )

        changed = await run(conn, log_conn, item("B", **{**ANSAN, "sprtTrgtMaxAge": "39"}))
        assert changed.counts["updated"] == 1  # 요건은 새로 저장했다
        assert (await rows(conn))["B"]["requirements_version"] == 2
        kept = await (
            await conn.execute(
                "select d.name, d.issuer, d.lead_days, t.title from opportunity_documents d"
                " left join planner_tasks t on t.document_id = d.id where d.opportunity_id = %s"
                " order by d.name",
                (policy_id,),
            )
        ).fetchall()
        assert kept == [
            {"name": "신청서", "issuer": "신청 사이트", "lead_days": 0, "title": None},
            {
                "name": "주민등록등본",
                "issuer": "정부24",
                "lead_days": 0,
                "title": "주민등록등본 준비",
            },
        ]
    finally:
        await cleanup(conn, log_conn)


async def test_retire_and_restore() -> None:
    """마감된 정책은 만료, 목록에서 사라진 정책은 숨김이다. 다시 나타나면 활성으로 돌린다."""
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)
        notice = await school_notice(conn, PREFIX + "E")
        await run(
            conn, log_conn, item("A"), item("B", **ANSAN), item("E", zipCd="41220"), item("S")
        )
        closed = await run(
            conn,
            log_conn,
            item("B", **{**ANSAN, "aplyPrdSeCd": "0057003"}),
            item("E", zipCd="26110"),
            item("S", aplyPrdSeCd="0057003"),
        )
        assert (closed.counts["expired"], closed.counts["hidden"]) == (2, 2)
        status = {name: row["status"] for name, row in (await rows(conn)).items()}
        # A는 목록에서 사라짐, E는 수도권 밖
        assert status == {"A": "hidden", "B": "expired", "E": "hidden", "S": "expired"}
        assert await status_of(conn, notice) == "active"  # 다른 출처의 공고는 그대로
        back = await run(conn, log_conn, item("A"), item("S"))
        assert back.counts["unchanged"] == 2  # 다시 상시가 된 S는 변환 결과가 마감 전과 같다
        status = {name: row["status"] for name, row in (await rows(conn)).items()}
        assert status == {"A": "active", "B": "expired", "E": "hidden", "S": "active"}
        # 마감 연장. 되돌릴 때 DB 시계(now())로 마감을 보므로 멀리 둔다
        longer = {**ANSAN, "aplyYmd": "20261101 ~ 20991231"}
        reopened = await run(conn, log_conn, item("B", **longer))
        assert reopened.counts["updated"] == 1
        assert (await rows(conn))["B"]["status"] == "active"
    finally:
        await cleanup(conn, log_conn)


async def test_expired_policy_past_deadline_stays_expired() -> None:
    """만료는 마감(DB 시계)이 지나지 않았을 때만 되돌린다. 수집한 날짜(today)와 DB 시계가 어긋나도
    지난 마감의 공고를 다시 열지 않는다."""
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)
        last_month = date(2026, 9, 15)
        september = {"aplyPrdSeCd": "0057001", "aplyYmd": "20260901 ~ 20260930"}
        await run(conn, log_conn, item("K", **september), today=last_month)
        await run(conn, log_conn, item("K", aplyPrdSeCd="0057003"), today=last_month)
        again = await run(conn, log_conn, item("K", **september), today=last_month)
        assert again.counts["unchanged"] == 1
        assert (await rows(conn))["K"]["status"] == "expired"
    finally:
        await cleanup(conn, log_conn)


async def test_many_missing_policies_are_not_hidden() -> None:
    """빠짐없이 받았다고 해도 한 번에 너무 많이 사라졌으면(온통청년 목록이 덜 옴) 숨기지 않는다."""
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)
        many = [item(f"M{n:02d}") for n in range(25)]
        await run(conn, log_conn, *many)
        cut = await run(conn, log_conn, *many[:4])  # 21건이 사라짐: 20건·활성의 20%를 넘음
        assert (cut.gone_kept, cut.counts["hidden"]) == (21, 0)
        assert {row["status"] for row in (await rows(conn)).values()} == {"active"}
        few = await run(conn, log_conn, *many[1:])  # 1건만 사라짐
        assert (few.gone_kept, few.counts["hidden"]) == (0, 1)
        assert (await rows(conn))["M00"]["status"] == "hidden"
        # 정말 내려갔으면 hide_gone(--hide-gone)으로 숨긴다
        forced = await collect(
            conn,
            using(log_conn),
            FakeClient(many[1:4]),
            today=TODAY,
            scenario=SCENARIO,
            hide_gone=True,
        )
        assert (forced.gone_kept, forced.counts["hidden"]) == (0, 21)
    finally:
        await cleanup(conn, log_conn)


async def test_incomplete_fetch_does_not_hide_missing() -> None:
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)
        await run(conn, log_conn, item("A"), item("B", **ANSAN))
        partial = await run(conn, log_conn, item("A"), skipped=(7,))
        assert partial.counts["hidden"] == 0
        assert (await rows(conn))["B"]["status"] == "active"
    finally:
        await cleanup(conn, log_conn)


async def test_feed_judgment_and_process_steps() -> None:
    """안산에 사는 22세 학부 재학생: 전국·안산 정책은 지원 가능, 평택 정책은 지원 어려움,
    취업 상태 조건이 있는 정책은 원문 확인 필요. 상세의 처리 과정은 온통청년 두 단계다."""
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)
        me = await make_user(
            conn,
            birth_date="2004-05-01",
            region_sido="경기도",
            region_sigungu="안산시 상록구",
            enrollment_status="enrolled",
            degree_program="bachelor",
        )
        await run(
            conn,
            log_conn,
            item("A"),
            item("B", **ANSAN),
            item("P", zipCd="41220"),
            item("J", jobCd="0013003"),
        )
        repo = OpportunityRepository(conn)
        await repo.refresh_judgments(me, now=NOW)
        page = await repo.feed_page(
            me, FeedQuery(source_types=("youth_policy",), limit=50), now=NOW
        )
        mine = {
            entry.title.removeprefix("청년정책 "): entry.eligibility.display_status
            for entry in page.items
            if entry.title.startswith("청년정책 ")
        }
        assert mine == {
            "A": "eligible",
            "B": "eligible",
            "J": "needs_review",
            "P": "ineligible",
        }
        b = (await rows(conn))["B"]
        detail = await repo.detail(me, str(b["id"]), now=NOW)
        steps = [(s.label, s.chosen_by, s.status) for s in detail.process.extraction]
        assert steps == [
            ("온통청년에서 정책 정보 받기", "pipeline", "succeeded"),
            ("온통청년 항목으로 지원 자격 정리", "pipeline", "succeeded"),
        ]
    finally:
        await cleanup(conn, log_conn)


async def test_age_is_judged_on_the_days_one_can_apply() -> None:
    """청년정책은 마감일 하나로 나이를 따지지 않는다(판정엔진_규칙.md 8장). 신청할 수 있는 첫날(오늘, 신청 기간
    전이면 시작일)과 마감일 중 맞는 날이 있으면 그 결과다. 끝난 정책은 마감일이다. 날이 바뀌면 다시 판정한다."""
    conn, log_conn = await connect(), await connect(autocommit=True)
    try:
        await skip_if_other_youth_policies(conn, PREFIX)
        older = await make_user(conn, birth_date="1992-01-01")  # 오늘 만 34세
        freshman = await make_user(conn, birth_date="2007-11-15")  # 오늘 만 18세, 11/15에 19세
        late = await make_user(conn, birth_date="1991-10-01")  # 9월에 만 34세, 10/1부터 35세
        teen = await make_user(conn, birth_date="2007-10-05")  # 9월에 만 18세, 10/5부터 19세
        ages = {"sprtTrgtMinAge": "19", "sprtTrgtMaxAge": "34", "aplyPrdSeCd": "0057001"}
        await run(
            conn,
            log_conn,
            item("E", **ages, aplyYmd="20260901 ~ 20260930"),
            today=date(2026, 9, 15),
        )
        await run(
            conn,
            log_conn,
            item("L", **ages, aplyYmd="20260101 ~ 20281231"),  # 몇 년짜리 신청 기간
            item("F", **ages, aplyYmd="20270101 ~ 20270131"),  # 아직 시작 전
            item("Y", **ages, aplyYmd="20261001 ~ 20261117"),  # 마감 전에 19세가 된다
            item("E", **ages, aplyYmd="20260901 ~ 20260930"),  # 끝남 → 만료
        )
        saved = await rows(conn)
        repo = OpportunityRepository(conn)

        async def judged(user: str, name: str) -> tuple[date | None, str]:
            found = (await repo.detail(user, str(saved[name]["id"]), now=NOW)).eligibility
            return found.basis_date, found.display_status

        # 오늘 만 34세라 지원 가능. 마감일(2028-12-31)로만 따지면 만 36세라 지원 어려움이 된다
        assert await judged(older, "L") == (TODAY, "eligible")
        assert await judged(older, "F") == (date(2027, 1, 1), "ineligible")  # 시작일에 만 35세
        # 오늘은 만 18세지만 마감일엔 19세: 지원 가능, 기준일은 마감일
        assert await judged(freshman, "Y") == (date(2026, 11, 17), "eligible")
        # 끝난 정책은 마감일(9/30, 만 34세)로 본다. 오늘(만 35세)로 다시 따지지 않는다
        assert saved["E"]["status"] == "expired"
        assert await judged(late, "E") == (date(2026, 9, 30), "eligible")
        assert await judged(teen, "E") == (date(2026, 9, 30), "ineligible")  # 오늘 19세여도

        # 상세에서 판정한 L·F는 그대로, 처음 보는 Y만 판정한다. 같은 날 다시 읽으면 0
        assert (await repo.refresh_judgments(older, now=NOW)).judged == 1
        assert (await repo.refresh_judgments(older, now=NOW)).judged == 0
        tomorrow = await repo.refresh_judgments(older, now=NOW + timedelta(days=1))
        assert tomorrow.judged == 3  # 신청 기간이 끝나지 않은 청년정책은 날마다 다시
        # 끝난 정책(E)은 날이 바뀌어도 다시 판정하지 않는다: 처음 보는 L·F·Y만
        later = await repo.refresh_judgments(
            late, now=NOW + timedelta(days=1), include_expired=True
        )
        assert later.judged == 3
    finally:
        await cleanup(conn, log_conn)
