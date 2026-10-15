"""포스터 추출 SQL (F-16).

- 올린 포스터 파일 찾기: 내 파일(origin = 'upload', kind = 'poster')만
- 중복 공고 찾기: 제목을 정규화해 같고 마감일이 같은 KST 날짜인 공고. 내가 볼 수 있는 공고만 본다
  (공개 범위는 공고 목록·상세와 같은 조건을 쓴다)

초안은 따로 저장하지 않고 그 실행이 남긴 tool_calls.output에 둔다. 다시 읽는 SQL은 실행 조회와 함께
repositories/runs.py에 있다(준비하기가 계획 행에서 결과를 다시 읽는 것과 같은 방식이다).
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from psycopg import AsyncConnection
from pydantic import ValidationError

from app.db import get_conn
from app.extraction.models import ExtractionResult
from app.extraction.store import content_hash, save_extraction
from app.extraction.validate import LOW_CONFIDENCE as LOW_CONFIDENCE_REASON
from app.posters.confirm import Confirmed
from app.posters.extract import LOW_CONFIDENCE
from app.repositories.opportunities import COURSE_JOIN, VISIBLE
from app.schemas.posters import EXTRACT_TOOL, DuplicateCandidate, PosterDraft

logger = logging.getLogger(__name__)
# 상세의 "원문 확인 필요" 이유. 공지 추출과 같은 기준이다(모호한 조건, 낮은 신뢰도)
AMBIGUOUS_REASON = "포스터에서 읽은 조건이라 더 확인해 봐야 해요"

# 제목 비교용 정규화: 영문 소문자·숫자·한글만 남긴다("2026 교내 장학" → "2026교내장학")
_NORMALIZED = "regexp_replace(lower({}), '[^0-9a-z가-힣]', '', 'g')"
_TITLE = _NORMALIZED.format("o.title")


@dataclass(frozen=True)
class PosterFile:
    id: str
    storage_path: str
    mime_type: str | None


@dataclass(frozen=True)
class StoredPoster:
    """추출 실행이 남긴 것. 등록할 때 기준으로 삼는다."""

    file_id: str | None
    draft: PosterDraft
    poster_text: str


class PosterRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def poster_file(self, user_id: str, file_id: str) -> PosterFile | None:
        """내가 올린 포스터 파일. 남의 파일·다른 종류·LMS 첨부는 None이다."""
        row = await (
            await self.conn.execute(
                "select id::text as id, storage_path, mime_type from files"
                " where id = %s and user_id = %s and origin = 'upload' and kind::text = 'poster'",
                (file_id, user_id),
            )
        ).fetchone()
        return None if row is None else PosterFile(row["id"], row["storage_path"], row["mime_type"])

    async def duplicate(
        self, user_id: str, *, title: str, deadline_at: datetime | None, now: datetime
    ) -> DuplicateCandidate | None:
        """같은 공고가 이미 있으면 그 공고. 제목이 같고 마감일이 같은 날이어야 한다.

        마감일을 읽지 못한 포스터는 아직 마감하지 않은 공고 중에서 제목이 같은 것을 본다. 제목만으로는
        "2026 1학기 교내장학"처럼 해마다 같은 이름인 공고를 엉뚱하게 묶을 수 있어서, 마감일이 있으면
        반드시 같은 KST 날짜여야 한다.
        """
        clean = _normalize(title)
        if not clean:
            return None
        params = {"uid": user_id, "title": clean, "deadline": deadline_at, "now": now}
        when = (
            " and (o.deadline_at at time zone 'Asia/Seoul')::date"
            " = (%(deadline)s::timestamptz at time zone 'Asia/Seoul')::date"
            if deadline_at is not None
            else " and (o.deadline_at is null or o.deadline_at >= %(now)s)"
        )
        row = await (
            await self.conn.execute(
                "select o.id::text as id, o.title from opportunities o"
                + COURSE_JOIN
                + " where o.status in ('active', 'expired') and "
                + VISIBLE
                + f" and {_TITLE} = %(title)s"
                + when
                + " order by o.deadline_at nulls last, o.id limit 1",
                params,
            )
        ).fetchone()
        return (
            None
            if row is None
            else DuplicateCandidate(opportunity_id=row["id"], title=row["title"])
        )

    async def stored(self, user_id: str, run_id: str) -> StoredPoster | None:
        """그 추출 실행이 남긴 초안·옮겨 적은 글·파일. 내 실행만이다.

        실행 상태는 보지 않는다. 초안은 도구가 끝날 때 한 번에 남으므로, 아직 돌고 있거나 실패한
        실행에는 초안이 없어 아래 검사에서 None이 된다.
        """
        row = await (
            await self.conn.execute(
                "select t.input, t.output from tool_calls t join agent_runs r on r.id = t.run_id"
                " where t.run_id = %s and r.user_id = %s and r.trigger_type = 'poster_upload'"
                " and t.tool_name = %s"
                " order by t.seq desc, t.id desc limit 1",
                (run_id, user_id, EXTRACT_TOOL),
            )
        ).fetchone()
        output = row["output"] if row else None
        if not isinstance(output, dict) or "draft" not in output:
            return None
        try:
            draft = PosterDraft.model_validate(output["draft"])
        except ValidationError:
            logger.warning("포스터 초안 모양이 달라 읽지 못했어요: run %s", run_id)
            return None
        source = row["input"] if isinstance(row["input"], dict) else {}
        file_id = source.get("file_id")
        return StoredPoster(
            file_id=str(file_id) if file_id else None,
            draft=draft,
            poster_text=str(output.get("poster_text") or ""),
        )

    async def create(
        self, user_id: str, *, run_id: str, stored: StoredPoster, confirmed: Confirmed
    ) -> str:
        """포스터 공고 행과 요건·서류를 만든다. 올린 본인에게만 보인다(공개 범위 규칙).

        요건·서류 저장은 공지 요건 추출과 같은 코드(extraction/store.save_extraction)를 쓴다.
        extraction_run_id가 붙어야 상세·피드가 판정을 쓴다.
        """
        reasons = []
        if any(item.is_ambiguous for item in confirmed.requirements):
            reasons.append(AMBIGUOUS_REASON)
        if confirmed.confidence < LOW_CONFIDENCE:
            reasons.append(LOW_CONFIDENCE_REASON)
        row = await (
            await self.conn.execute(
                "insert into opportunities (source_type, category, title, organizer, raw_text,"
                " uploaded_by, poster_file_id) values ('poster', %s::opportunity_category, %s, %s,"
                " %s, %s, %s) returning id::text as id",
                (
                    confirmed.category,
                    confirmed.title,
                    confirmed.organizer,
                    stored.poster_text or None,
                    user_id,
                    stored.file_id,
                ),
            )
        ).fetchone()
        assert row is not None
        opportunity_id = row["id"]
        await save_extraction(
            self.conn,
            opportunity_id,
            ExtractionResult(
                succeeded=True,
                requirements=confirmed.requirements,
                documents=confirmed.documents,
                apply_start_at=confirmed.apply_start_at,
                deadline_at=confirmed.deadline_at,
                easy_summary=confirmed.easy_summary,
                confidence=confirmed.confidence,
                needs_review=bool(reasons),
                review_reasons=tuple(reasons),
            ),
            run_id=run_id,
            content_hash=content_hash(stored.poster_text, ()),
        )
        return opportunity_id


def _normalize(title: str) -> str:
    """SQL의 _TITLE과 같은 규칙. 아스키 소문자·숫자와 한글만 남긴다.

    전각 숫자("２")나 한자는 SQL 쪽 [^0-9a-z가-힣]도 지우므로 여기서도 지운다. 두 규칙이 어긋나면
    코드가 찾은 제목과 DB가 비교하는 제목이 달라져 중복을 놓친다.
    """
    return "".join(ch for ch in title.lower() if _kept(ch))


def _kept(ch: str) -> bool:
    return "0" <= ch <= "9" or "a" <= ch <= "z" or "가" <= ch <= "힣"


def get_poster_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> PosterRepository:
    return PosterRepository(conn)


PosterRepoDep = Annotated[PosterRepository, Depends(get_poster_repo)]
