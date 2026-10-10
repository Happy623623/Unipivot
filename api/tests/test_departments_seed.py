"""학과 목록 seed(supabase/migrations/20261010000100_seed_departments.sql)를 적용한 DB를 확인한다.

CI와 같이 마이그레이션을 모두 적용한 DB에서 돈다. DATABASE_URL이 있을 때만 돈다.
"""

from datetime import date

import pytest

from app.eligibility import Profile, Requirement, check_eligibility
from app.extraction.store import load_departments
from app.repositories.meta import MetaRepository
from tests.db_world import DATABASE_URL, connect

pytestmark = [
    pytest.mark.db,
    pytest.mark.anyio,
    pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀"),
]

# 한양대학교 대학/학과 소개의 ERICA 단과대학 순서
COLLEGES = [
    "공학대학",
    "소프트웨어융합대학",
    "약학대학",
    "첨단융합대학",
    "글로벌문화통상대학",
    "커뮤니케이션&컬처대학",
    "경상대학",
    "디자인대학",
    "예체능대학",
    "LIONS칼리지",
]
FIELD_GROUPS = {
    "공학계열",
    "자연계열",
    "의약계열",
    "인문계열",
    "사회계열",
    "예체능계열",
    "자율전공",
}


async def test_seeded_departments() -> None:
    conn = await connect()
    try:
        rows = await (
            await conn.execute(
                "select name, college, field_group, sort_order, is_active from departments"
                " where sort_order >= 100 order by sort_order"
            )
        ).fetchall()
        assert len(rows) == 48 and all(row["is_active"] for row in rows)
        assert list(dict.fromkeys(row["college"] for row in rows)) == COLLEGES
        assert {row["field_group"] for row in rows} == FIELD_GROUPS
        by_name = {row["name"]: (row["college"], row["field_group"]) for row in rows}
        # 다른 테스트와 가짜 저장소(tests/fakes.py)가 쓰는 학과와 같은 값이다
        assert by_name["인공지능학과"] == ("소프트웨어융합대학", "공학계열")
        assert by_name["경영학부"] == ("경상대학", "사회계열")
        assert by_name["약학과"] == ("약학대학", "의약계열")
        # 가운뎃점은 U+00B7 하나로 쓴다(학교 글에는 ㆍ도 섞여 있다)
        assert "교통·물류공학과" in by_name and "주얼리·패션디자인학과" in by_name
        assert not any("ㆍ" in name or " " in name for name in by_name)

        # 온보딩 목록(GET /meta/departments)과 요건 추출 프롬프트가 같은 목록을 쓴다
        listed = [department.name for department in await MetaRepository(conn).list_departments()]
        assert [name for name in listed if name in by_name] == list(by_name)
        assert {department.name for department in await load_departments(conn)} >= set(by_name)
    finally:
        await conn.rollback()
        await conn.close()


async def test_seeded_departments_judge_college_and_field_group() -> None:
    """단과대학·계열 조건이 seed 목록으로 판정된다. 목록에 없는 이름("이공계")은 불충족으로 보지 않는다."""
    conn = await connect()
    try:
        departments = await load_departments(conn)

        def judge(department: str, basis: str, *names: str) -> str:
            requirement = Requirement(
                id="r1",
                clause_no=1,
                field="department",
                operator="in",
                value=list(names),
                basis=basis,
            )
            judgment = check_eligibility(
                [requirement],
                Profile(department=department),
                basis_date=date(2026, 10, 10),
                departments=departments,
            )
            return judgment.status

        assert judge("인공지능학과", "college", "소프트웨어융합대학") == "eligible"
        assert judge("수리데이터사이언스학과", "field_group", "공학계열", "자연계열") == "eligible"
        assert judge("경영학부", "field_group", "공학계열", "자연계열") == "ineligible"
        assert judge("경영학부", "field_group", "이공계") == "undetermined"
    finally:
        await conn.rollback()
        await conn.close()
