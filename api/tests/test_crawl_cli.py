"""공지 가져오기 CLI: check(폴더 확인·형식 집계), list(저장한 목록), import(DB, 가짜 LLM)."""

import os
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.crawl import cli
from app.crawl.cli import main
from app.crawl.hanyang import BOARD_URL
from app.extraction import ExtractionAgent
from app.extraction.prompt import READ_TEXT, SUBMIT
from tests import hanyang_pages, samples
from tests.hanyang_pages import FILES, POSTER, save_notice
from tests.llm_fakes import ScriptedLlm, call
from tests.samples import hp

pytestmark = pytest.mark.anyio
DATABASE_URL = os.environ.get("DATABASE_URL", "")
GUIDE = samples.hwpx(hp("가. 직전 학기 평점평균 3.0 이상인 재학생"))
FORM = samples.pdf(["장학금 신청서\n학번, 이름, 연락처를 적고 서명한 뒤 학생지원팀에 낸다."])
POSTER_IMG = f'<p><img alt="포스터" src="./{FILES}/poster.jpg"></p>'


def docx() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def notices(root: Path) -> Path:
    """공지 폴더 셋: ERICA(다 있음), ERICA(첨부 하나 빠짐), 서울."""
    save_notice(
        root / "1 장학",
        hanyang_pages.detail(
            entry_id=119702,
            files=("1. 선발요강.hwpx", "2. 신청서.pdf", "3. 동의서.docx"),
            body="<p>신청 기간: 10. 24.(금) 18:00까지</p>" + POSTER_IMG,
        ),
        {
            "1. 선발요강.hwpx": GUIDE,
            "2. 신청서.pdf": FORM,
            "3. 동의서.docx": docx(),
            "메모.txt": b"x",  # 페이지 첨부가 아닌 파일
        },
        {"poster.jpg": POSTER},
    )
    save_notice(
        root / "2 근로",
        hanyang_pages.detail(entry_id=119703, files=("1. 모집 공고.pdf",)),
        {},
    )
    save_notice(
        root / "3 서울",
        hanyang_pages.detail(entry_id=119704, campus="서울", files=()),
        {},
    )
    return root


async def test_check_pairs_files_and_counts_formats(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = notices(tmp_path / "공지")
    assert await main(["check", str(root)]) == 1  # 고칠 것(빠진 첨부)이 있다
    out = capsys.readouterr().out
    assert "[1/3] 1 장학" in out and "[3/3] 3 서울" in out
    assert "글 119702 · 2026-09-30 · 장학/등록(scholarship) · 캠퍼스 ERICA → 가져올 대상" in out
    assert "    첨부 1. 1. 선발요강.hwpx — HWPX, 글자 " in out  # 모델이 보는 첨부 목록과 같은 줄
    assert "    첨부 3. 3. 동의서.docx — 못 읽음: DOCX는 아직 못 읽어요" in out
    assert "    본문 이미지 4. poster.jpg — 이미지(JPG)" in out
    assert "    첨부 1. 1. 모집 공고.pdf — 폴더에 없어요" in out
    assert "    폴더에만 있는 파일(안 씀): 메모.txt" in out
    assert "→ 건너뜀(서울)" in out
    assert "공지 가져올 대상 1 · 고칠 것 1 · 건너뜀(서울) 1" in out
    for line in (
        "HWPX: 1",
        "PDF 글자: 1",
        "못 읽음(DOCX): 1",
        "이미지(Vision): 1",
        "가져오지 못함: 1",
    ):
        assert f"    {line}" in out

    assert await main(["check", str(root / "1 장학")]) == 0


async def test_same_notice_in_two_folders_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    html = hanyang_pages.detail(entry_id=119710, files=())
    save_notice(tmp_path / "공지" / "10월 8일 저장", html, {})
    save_notice(tmp_path / "공지" / "10월 9일 저장", html.replace("자세한", "고친"), {})
    assert await main(["check", str(tmp_path / "공지")]) == 1
    out = capsys.readouterr().out
    message = (
        "같은 글(119710)이 폴더 2개에 있어요(10월 8일 저장, 10월 9일 저장)."
        " 최근에 저장한 폴더 하나만 남기세요"
    )
    assert out.count(message) == 2  # 실행마다 번갈아 다시 추출하지 않게 둘 다 멈춘다

    # 새 저장본 폴더가 페이지 두 개 때문에 읽히지 않아도, 옛 저장본만 들어가지 않게 둘 다 멈춘다
    other = tmp_path / "다른 공지"
    save_notice(other / "옛 저장", hanyang_pages.detail(entry_id=119730, files=()), {})
    fresh = save_notice(other / "새 저장", hanyang_pages.detail(entry_id=119730, files=()), {})
    (fresh / "실수로 같이 저장.html").write_text(hanyang_pages.listing([]), encoding="utf-8")
    assert await main(["check", str(other)]) == 1
    out = capsys.readouterr().out
    assert out.count("같은 글(119730)이 폴더 2개에 있어요(새 저장, 옛 저장)") == 2


async def test_list_shows_erica_and_common_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = tmp_path / "목록.html"
    rows = [
        (120202, "애스크톤 예선 결과", "한양", "일반"),
        (120201, "전공박람회", "서울", "행사"),
        (119902, "입학설명회", None, "행사"),
    ]
    page.write_text(
        hanyang_pages.listing(
            [
                {
                    "entry_id": entry_id,
                    "title": title,
                    "campus": campus,
                    "category": category,
                    "department": "학생지원팀",
                    "posted": "2026. 10. 8",
                }
                for entry_id, title, campus, category in rows
            ]
        ),
        encoding="utf-8",
    )
    assert await main(["list", str(page)]) == 0
    out = capsys.readouterr().out
    assert "목록 3건 중 ERICA·공통 2건(서울 1건은 뺌)" in out
    assert "120202  2026-10-08  한양  일반  애스크톤 예선 결과" in out
    assert "119902  2026-10-08  표시 없음  행사  입학설명회" in out
    assert "전공박람회" not in out
    assert await main(["list", str(tmp_path / "없는 파일.html")]) == 1


async def test_import_explains_db_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = notices(tmp_path / "공지")
    monkeypatch.setenv("DATABASE_URL", "")
    assert await main(["import", str(root)]) == 1
    assert "DATABASE_URL이 없어요" in capsys.readouterr().out
    # 닫힌 포트. 보안 프로그램이 응답 없이 버리는 PC에서도 2초 안에 끝나게 시간 제한을 준다
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none?connect_timeout=2")
    assert await main(["import", str(root)]) == 1
    assert "DB에 연결하지 못했어요" in capsys.readouterr().out
    assert await main(["import", str(tmp_path / "빈 폴더")]) == 1  # 폴더가 없다
    assert "폴더가 없어요" in capsys.readouterr().out


async def test_db_connect_gives_up_after_ten_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """주소에 connect_timeout이 없으면 10초만 기다린다. psycopg 기본값은 130초다."""
    seen: list[Any] = []

    async def connect(conninfo: str, **kwargs: Any) -> None:
        seen.append(kwargs.get("connect_timeout"))
        raise psycopg.OperationalError("연결 안 됨")

    monkeypatch.setattr(cli.AsyncConnection, "connect", connect)
    url = "postgresql://u:p@db.example/x"
    for database_url in (url, f"{url}?connect_timeout=30"):
        with pytest.raises(psycopg.OperationalError):
            await cli._connect(database_url)
    assert seen == [cli.CONNECT_TIMEOUT, None]  # 주소에 있으면 주소 값을 쓴다


async def _cleanup(scenario: str, entry_ids: tuple[str, ...]) -> None:
    """이 테스트가 만든 행만 지운다. CLI는 autocommit이라 되돌릴 수 없다."""
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        await conn.execute(
            "delete from opportunities o using sources s where s.id = o.source_id"
            " and s.base_url = %s and o.external_id = any(%s)",
            (BOARD_URL, list(entry_ids)),
        )
        await conn.execute(
            "delete from sources s where s.base_url = %s"
            " and not exists (select 1 from opportunities o where o.source_id = s.id)",
            (BOARD_URL,),
        )
        await conn.execute("delete from agent_runs where scenario_code = %s", (scenario,))


async def _runs(scenario: str) -> list[tuple]:
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        cursor = await conn.execute(
            "select scenario_code, status from agent_runs where scenario_code = %s order by started_at",
            (scenario,),
        )
        return await cursor.fetchall()


@pytest.mark.db
@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀")
async def test_import_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    scenario = f"S10-test-{uuid.uuid4().hex[:8]}"
    root = notices(tmp_path / "공지")
    (root / "2 근로" / "1. 모집 공고.pdf").write_bytes(FORM)  # 빠진 첨부를 넣었다
    scripts = [
        [  # 1 장학
            call(READ_TEXT, attachment_no=1, reason="자격이 선발요강에 있어서 읽음"),
            call(
                SUBMIT,
                requirements=[
                    {
                        "clause_no": 1,
                        "field": "gpa_last_semester",
                        "operator": "gte",
                        "value_json": "3.0",
                        "evidence_text": "직전 학기 평점평균 3.0 이상",
                        "is_ambiguous": False,
                    }
                ],
                documents=[{"name": "장학금 신청서", "is_required": True, "form_attachment_no": 2}],
                deadline="2026-10-24T18:00",
                confidence=0.9,
                needs_review=False,
            ),
        ],
        [call(SUBMIT, requirements=[], documents=[], confidence=0.8, needs_review=False)],  # 2 근로
    ]
    made: list[dict[str, Any]] = []

    def make_agent(settings: Any, **options: Any) -> ExtractionAgent:
        made.append(options)
        replies = [reply for script in scripts for reply in script]
        scripts.clear()  # 두 번째 실행에서는 답이 없다(모델을 부르면 실패)
        return ExtractionAgent(ScriptedLlm(*replies), model="gemini-3.8-flash")

    try:
        argv = ["import", str(root), "--scenario", scenario]
        assert await main(argv, make_agent=make_agent) == 0
        out = capsys.readouterr().out
        assert made[0]["fetch_page"] is None  # 학교 서버를 다시 읽지 않는다
        assert "모델 gemini-3.8-flash · 학과 " in out and "공지 폴더 3개" in out
        assert "    폴더에만 있는 파일(안 씀): 메모.txt" in out
        assert "    새 공고 · 요건 1개 · 서류 1개 · 마감 2026-10-24 18:00 · 신뢰도 0.90 · $" in out
        assert "    원문 확인 필요: 읽지 못한 첨부가 있음" in out  # 3. 동의서.docx
        assert "    원문 확인 필요: 첨부를 읽지 않고 요건 없음으로 판단" in out  # 2 근로
        assert "    건너뜀: 서울캠퍼스 공지라 건너뜀" in out
        assert "새 공고 2 · 다시 추출 0 · 그대로 0 · 건너뜀 1 · 오류 0 · 판정 안 됨 0" in out

        assert await main(["import", str(root), "--scenario", scenario], make_agent=make_agent) == 0
        out = capsys.readouterr().out
        assert out.count("그대로: 내용이 같아 다시 추출하지 않음") == 2
        assert "새 공고 0 · 다시 추출 0 · 그대로 2 · 건너뜀 1 · 오류 0 · 판정 안 됨 0" in out
        assert await _runs(scenario) == [(scenario, "succeeded")] * 2  # 두 번째 실행은 0번

        listing = tmp_path / "목록.html"
        listing.write_text(
            hanyang_pages.listing(
                [
                    {
                        "entry_id": entry_id,
                        "title": f"글 {entry_id}",
                        "campus": "ERICA",
                        "category": "장학/등록",
                        "department": "학생지원팀",
                        "posted": "2026. 10. 8",
                    }
                    for entry_id in (119702, 119800)
                ]
            ),
            encoding="utf-8",
        )
        assert await main(["list", str(listing), "--db"]) == 0
        out = capsys.readouterr().out
        assert "119800  2026-10-08  ERICA  장학/등록  새 글  글 119800" in out
        assert "119702  2026-10-08  ERICA  장학/등록  가져옴  글 119702" in out
    finally:
        await _cleanup(scenario, ("119702", "119703"))


@pytest.mark.db
@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL이 없어서 DB 통합 테스트를 건너뜀")
async def test_import_reports_failed_extraction_and_duplicates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    scenario = f"cli-test-{uuid.uuid4().hex[:8]}"
    root = tmp_path / "공지"
    save_notice(root / "가", hanyang_pages.detail(entry_id=119720, files=()), {})
    twin = hanyang_pages.detail(entry_id=119721, files=())
    save_notice(root / "나", twin, {})
    save_notice(root / "다", twin, {})  # 같은 글을 두 번 저장했다

    def silent_agent(settings: Any, **options: Any) -> ExtractionAgent:
        return ExtractionAgent(ScriptedLlm("요건은…", "그러니까…"), model="gemini-3.8-flash")

    try:
        argv = ["import", str(root), "--scenario", scenario]
        assert await main(argv, make_agent=silent_agent) == 1
        out = capsys.readouterr().out
        assert "    새 공고 · 추출 실패(제출 없음) → 판정하지 않음 · $" in out
        assert "    지난 추출이 실패해 판정에서 빠져 있어요. --force로 다시 추출하세요" in out
        assert out.count("    오류: 같은 글(119721)이 폴더 2개에 있어요(나, 다).") == 2
        assert "새 공고 1 · 다시 추출 0 · 그대로 0 · 건너뜀 0 · 오류 2 · 판정 안 됨 1" in out

        assert await main(argv, make_agent=silent_agent) == 1  # 다음 실행에도 알려 준다
        out = capsys.readouterr().out
        assert "그대로: 내용이 같아 다시 추출하지 않음. 지난 추출이 실패해" in out
        assert "판정 안 됨 1" in out
    finally:
        await _cleanup(scenario, ("119720", "119721"))
