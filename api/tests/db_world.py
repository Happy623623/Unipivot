"""DB 통합 테스트가 같이 쓰는 공고·사용자 묶음(S1-5·S1-6). 모두 호출한 쪽의 트랜잭션 안에서 만든다."""

import os
import uuid
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.repositories.profiles import ProfileRepository
from app.schemas.opportunities import OpportunityItem

DATABASE_URL = os.environ.get("DATABASE_URL", "")
COURSE = 777_001  # 수강 중인 과목
Requirement = tuple[int, str, str, Any]  # (clause_no, field, operator, value)


async def connect(autocommit: bool = False) -> psycopg.AsyncConnection:
    """테스트 연결. 실행 로그(agent_run)를 남길 연결은 autocommit이어야 한다."""
    return await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row, autocommit=autocommit, prepare_threshold=None
    )


async def make_user(conn: psycopg.AsyncConnection, **profile: Any) -> str:
    user_id = str(uuid.uuid4())
    await conn.execute("insert into auth.users (id) values (%s)", (user_id,))
    repo = ProfileRepository(conn)
    await repo.ensure(user_id, "테스트 학생")
    await repo.save_consent(user_id, "2026-10-07", agree_income_info=False)
    if profile:
        await repo.update_profile(user_id, profile)
    return user_id


async def judged_titles(conn: psycopg.AsyncConnection, user_id: str) -> set[str]:
    """이 사용자의 판정이 저장된 공고 제목."""
    rows = await (
        await conn.execute(
            "select o.title from eligibility_results e join opportunities o"
            " on o.id = e.opportunity_id where e.user_id = %s",
            (user_id,),
        )
    ).fetchall()
    return {row["title"] for row in rows}


class World:
    """한 트랜잭션 안의 공고 묶음. now는 트랜잭션 시작 시각(DB now())이다."""

    def __init__(self, conn: psycopg.AsyncConnection, now: datetime, run_id: str) -> None:
        self.conn, self.now, self.run_id = conn, now, run_id
        self.ids: dict[str, str] = {}

    @classmethod
    async def start(cls, conn: psycopg.AsyncConnection) -> "World":
        run = await (
            await conn.execute(
                "insert into agent_runs (trigger_type, status) values ('batch_crawl', 'succeeded')"
                " returning id, started_at as now"
            )
        ).fetchone()
        assert run is not None
        return cls(conn, run["now"], str(run["id"]))

    async def add(
        self,
        title: str,
        *,
        days: float | None,
        requirements: tuple[Requirement, ...] = (),
        extracted: bool = True,
        **columns: Any,
    ) -> str:
        values = {
            "source_type": "school_notice",
            "category": "scholarship",
            "title": title,
            "organizer": "학생지원팀",
            "easy_summary": f"{title} 쉬운 설명",
            "deadline_at": None if days is None else self.now + timedelta(days=days),
            "extraction_run_id": self.run_id if extracted else None,
            **columns,
        }
        names = ", ".join(values)
        marks = ", ".join(["%s"] * len(values))
        row = await (
            await self.conn.execute(
                f"insert into opportunities ({names}) values ({marks}) returning id",
                tuple(values.values()),
            )
        ).fetchone()
        assert row is not None
        opportunity_id = str(row["id"])
        for index, (clause_no, field, operator, value) in enumerate(requirements):
            await (
                self.conn.execute(  # 추출 저장(save_extraction)처럼 넣은 순서를 created_at에 남긴다
                    "insert into requirements (opportunity_id, clause_no, field, operator, value,"
                    " evidence_text, created_at)"
                    " values (%s, %s, %s, %s, %s, %s, now() + %s * interval '1 microsecond')",
                    (
                        opportunity_id,
                        clause_no,
                        field,
                        operator,
                        Jsonb(value),
                        f"{title} 근거",
                        index,
                    ),
                )
            )
        self.ids[title] = opportunity_id
        return opportunity_id


async def build(conn: psycopg.AsyncConnection) -> tuple[World, str, str]:
    """사용자 둘과 공고 13개. 보이는 활성 공고는 8개다."""
    await conn.execute(
        "insert into departments (name, college, field_group) values"
        " ('인공지능학과', '소프트웨어융합대학', '공학계열') on conflict do nothing"
    )
    me = await make_user(
        conn,
        department="인공지능학과",
        grade=3,
        credits_last_semester=10,
        gpa_last_semester=3.5,
    )
    other = await make_user(conn)
    await conn.execute(
        "insert into lms_courses (user_id, canvas_course_id, name) values (%s, %s, %s)",
        (me, COURSE, "202620HY23525_선형대수"),
    )
    world = await World.start(conn)
    old = world.now - timedelta(days=40)
    await world.add("장학 A", days=2, requirements=((1, "gpa_last_semester", "gte", 3.0),))
    await world.add("장학 B", days=10, requirements=((1, "credits_last_semester", "gte", 12),))
    await world.add(
        "교내 C",
        days=5,
        category="school_program",
        requirements=((1, "income_bracket", "lte", 8),),
    )
    await world.add(
        "기타 D",
        days=1,
        category="etc",
        requirements=((1, "other", "eq", {"text": "면접 통과자"}),),
    )
    await world.add("실패 E", days=3, extracted=False, needs_review=True)
    await world.add("상시 F", days=None, category="activity", created_at=old)
    await world.add("지난 G", days=-1)
    await world.add("남의 포스터 H", days=20, source_type="poster", uploaded_by=other)
    await world.add(
        "내 포스터 I", days=20, category="contest", source_type="poster", uploaded_by=me
    )
    await world.add(
        "과목 공지 J",
        days=7,
        category="school_program",
        source_type="lms_announcement",
        visible_canvas_course_id=COURSE,
    )
    await world.add(
        "다른 과목 K", days=7, source_type="lms_announcement", visible_canvas_course_id=888
    )
    await world.add("숨김 L", days=4, status="hidden")
    await world.add("만료 M", days=-3, status="expired")
    await conn.execute(
        "insert into prep_plans (user_id, opportunity_id) values (%s, %s)",
        (me, world.ids["장학 A"]),
    )
    await conn.execute(
        "insert into opportunity_views (user_id, opportunity_id) values (%s, %s)",
        (me, world.ids["장학 B"]),
    )
    return world, me, other


def titles(items: list[OpportunityItem], world: World) -> list[str]:
    names = {opportunity_id: title for title, opportunity_id in world.ids.items()}
    return [names[item.id] for item in items]
