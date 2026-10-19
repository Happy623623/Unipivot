"""시나리오 실행의 DB 없이 볼 수 있는 부분: 고르기·출력·녹화 응답·안전장치(app/eval)."""

import logging
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.calendar.google import GoogleCalendarError, GoogleEvent
from app.config import Settings
from app.eligibility import KST
from app.eval.cli import _moment, main, managed_database
from app.eval.fakes import (
    DB_COURSE_ID,
    LMS_USER_ID,
    ML_COURSE_ID,
    RecordedCalendar,
    RecordedLearningX,
    RecordedLlm,
    RecordedStorage,
    course_week,
    lms_moment,
    nationwide,
    poster_bytes,
    poster_submit,
    semester_code,
    semester_start,
    sido_codes,
    youth_policy,
)
from app.eval.models import Check, CheckFailed, Report, ScenarioResult, percentile, plain
from app.eval.runner import _check_drained, run_scenarios
from app.eval.scenarios import SCENARIOS, pick
from app.eval.syllabus import (
    FINAL_LINE,
    FINAL_WEEK,
    MIDTERM_LINE,
    MIDTERM_WEEK,
    PRESENTATION_LINE,
    PRESENTATION_WEEK,
    SYLLABUS_TEXT,
    syllabus_pdf,
)
from app.eval.world import DEFAULT_NOW, eval_settings
from app.llm import Blob, UserTurn
from app.posters.prompt import SUBMIT
from app.syllabi.extract import SEMESTER_DAYS
from app.uploads import inspect_syllabus, pdf_text
from app.uploads.storage import StorageError, StorageMissing

pytestmark = pytest.mark.anyio

# PRD 8장 표에서 지금까지 만든 시나리오. S09·S10은 실제 HWP·PDF 파일이 먼저다.
# S22·S23은 P1이지만 F-53과 함께 만들었다(기회성 공지 → 공고 → 판정)
EXPECTED_CODES = (
    "S01",
    "S02",
    "S03",
    "S04",
    "S05",
    "S06",
    "S07",
    "S08",
    "S11",
    "S12",
    "S13",
    "S14",
    "S15",
    "S16",
    "S17",
    "S18",
    "S22",
    "S23",
)


@pytest.fixture(autouse=True)
def _keep_log_levels() -> Iterator[None]:
    """CLI는 바깥 호출 로그를 끈다(프로세스 전체에 남는다). 이 파일 밖으로 새지 않게 돌려 놓는다."""
    http = logging.getLogger("httpx")
    level = http.level
    yield
    http.setLevel(level)


def test_the_scenario_list_matches_the_prd_table() -> None:
    assert tuple(scenario.code for scenario in SCENARIOS) == EXPECTED_CODES
    # 우선순위는 PRD 표 그대로다(S23만 P1)
    assert {scenario.code for scenario in SCENARIOS if scenario.priority != "P0"} == {
        "S22",
        "S23",
    }
    assert all(scenario.title and scenario.run.__doc__ for scenario in SCENARIOS)


def test_picking_scenarios_by_code() -> None:
    assert [scenario.code for scenario in pick(None)] == list(EXPECTED_CODES)
    assert [scenario.code for scenario in pick(["S13", "S01"])] == ["S13", "S01"]
    with pytest.raises(KeyError, match="S99"):
        pick(["S01", "S99"])
    with pytest.raises(KeyError, match="번호를 적어"):
        pick([])  # --scenarios "," 로 전부 돌아 버리지 않게


def test_a_real_supabase_url_is_refused() -> None:
    """시나리오는 사용자·공고를 만들고 지운다. 실제 DB에서 돌면 남의 데이터를 지운다."""
    problem = managed_database("postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres")
    assert problem is not None
    assert "abcdefgh" not in problem and "pw" not in problem  # 주소·비밀번호를 보여 주지 않는다
    assert managed_database("postgresql://postgres:postgres@localhost:5432/unipivot_test") is None


async def test_the_runner_itself_refuses_a_supabase_url() -> None:
    """CLI만 막으면 pytest로 부를 때 샌다(테스트도 run_scenarios를 바로 부른다)."""
    with pytest.raises(RuntimeError, match="Supabase"):
        await run_scenarios("postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres", [])


async def test_the_cli_refuses_a_supabase_url_before_connecting(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres"
    monkeypatch.setattr("app.eval.cli.Settings", lambda: Settings(database_url=url))
    assert await main(["--scenarios", "S02"]) == 1
    printed = capsys.readouterr().out
    assert "Supabase" in printed and "abcdefgh" not in printed


def test_the_clock_can_be_given_without_a_time_zone() -> None:
    assert _moment(None) == DEFAULT_NOW
    assert _moment("2026-10-12T09:00:00+09:00") == DEFAULT_NOW
    assert _moment("2026-10-12T09:00") == DEFAULT_NOW  # 시간대를 적지 않으면 KST
    assert _moment("2026-03-01T00:00:00Z").astimezone(KST).date() == date(2026, 3, 1)
    with pytest.raises(ValueError, match="--now"):
        _moment("내일")


async def test_the_cli_stops_without_a_database_url(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # api/.env나 CI에 DATABASE_URL이 있어도 같은 결과여야 한다
    monkeypatch.setattr("app.eval.cli.Settings", lambda: Settings(database_url=""))
    assert await main(["--scenarios", "S01"]) == 1
    assert "DATABASE_URL" in capsys.readouterr().out


async def test_the_cli_lists_scenarios_without_touching_the_database(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await main(["--list"]) == 0
    printed = capsys.readouterr().out
    assert all(code in printed for code in EXPECTED_CODES)


async def test_the_cli_quiets_the_outside_call_log() -> None:
    """결과 표만 보이게 한다. 서버 로그에서는 그대로 남긴다(키를 가려 적는 것을 시험이 지킨다)."""
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    assert await main(["--list"]) == 0
    assert logging.getLogger("httpx").level == logging.WARNING


async def test_an_unknown_scenario_is_named(capsys: pytest.CaptureFixture[str]) -> None:
    assert await main(["--scenarios", "S42"]) == 1
    assert "S42" in capsys.readouterr().out


@pytest.mark.parametrize("raw", [",", " ", ""])
async def test_an_empty_scenario_list_is_not_everything(
    raw: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """--scenarios를 비워 적으면 전부 돌지 않는다(전부 돌면 DB에 열여섯 개를 만들고 지운다)."""
    assert await main(["--scenarios", raw]) == 1
    assert "번호를 적어" in capsys.readouterr().out


def test_an_unfinished_background_job_fails_the_scenario() -> None:
    """뒤에서 도는 일을 못 끝내면 비용이 빠지고 기록도 반쪽이 된다."""
    assert _check_drained(0, "S01") is None
    with pytest.raises(TimeoutError, match="S01"):
        _check_drained(2, "S01")


def test_settings_never_reuse_the_real_login_secret() -> None:
    first, second = eval_settings("postgresql://x/y"), eval_settings("postgresql://x/y")
    assert first.supabase_jwt_secret and first.supabase_jwt_secret != second.supabase_jwt_secret
    assert first.token_encryption_key != second.token_encryption_key
    assert first.supabase_url == ""  # 공개키를 받으러 나가지 않는다(HS256으로 검증)
    assert first.database_url == "postgresql://x/y"


def test_a_check_records_both_sides() -> None:
    assert Check("판정", "eligible", "eligible").ok
    failed = Check("판정", "eligible", "ineligible")
    assert not failed.ok
    assert failed.json() == {
        "what": "판정",
        "expected": "eligible",
        "actual": "ineligible",
        "ok": False,
    }
    assert "기대 'eligible'" in str(CheckFailed(failed))


def test_values_are_turned_into_json_before_they_are_stored() -> None:
    assert plain({"when": datetime(2026, 10, 12, 9, tzinfo=KST)}) == {
        "when": "2026-10-12T09:00:00+09:00"
    }
    # 집합은 순서를 정해 준다. 정수는 해시가 고정이라 {8, 1}은 그대로 쓰면 [8, 1] 순서로 나온다
    assert plain({8, 1}) == [1, 8]
    assert plain({"fields", "clauses"}) == ["clauses", "fields"]
    assert plain([Decimal("0.5"), (1, date(2026, 1, 2))]) == [0.5, [1, "2026-01-02"]]


def test_percentiles_pick_one_of_the_measured_values() -> None:
    """시나리오가 몇 개뿐이라 값을 섞지 않는다(가장 가까운 순위)."""
    assert percentile([], 50) == 0
    assert percentile([7], 95) == 7
    assert percentile([10, 20, 30, 40], 50) == 20
    assert percentile([10, 20, 30, 40], 95) == 40


def test_the_report_sums_what_the_baseline_keeps() -> None:
    report = Report(
        now=DEFAULT_NOW,
        priced_on=date(2026, 10, 15),
        results=[
            ScenarioResult(
                "S01", "하나", True, 100, api_ms=7.5, cost_usd=Decimal("0.001"), llm_calls=1
            ),
            ScenarioResult("S02", "둘", False, 300, error="판정: 기대 …", llm_calls=2),
        ],
    )
    saved = report.json()
    assert (saved["passed"], saved["scenarios"], saved["success_rate"]) == (1, 2, 0.5)
    assert saved["latency_ms"] == {"p50": 100, "p95": 300}
    assert (saved["cost_usd"], saved["llm_calls"]) == (0.001, 3)
    assert saved["now"] == "2026-10-12T09:00:00+09:00"
    # 단가는 돌린 날로 고른다. 베이스라인끼리 비교할 때 이 날짜가 같아야 비용을 비교할 수 있다
    assert saved["priced_on"] == "2026-10-15"
    assert saved["api_ms"] == 7.5 and saved["results"][0]["api_ms"] == 7.5
    assert saved["results"][1]["error"] == "판정: 기대 …"


async def test_the_recorded_model_answers_in_order_and_then_complains() -> None:
    llm = RecordedLlm("첫 답")
    reply = await llm.generate(
        model="gemini-vision",
        system="규칙",
        turns=[UserTurn("보기", (Blob(b"\xff", "image/jpeg"),))],
    )
    assert reply.turn.text == "첫 답"
    assert llm.asks[0].blobs == [Blob(b"\xff", "image/jpeg")]
    assert reply.usage.input_tokens > 0  # 비용이 0이 되지 않게 토큰을 녹화해 둔다
    with pytest.raises(AssertionError, match="녹화한 답보다"):
        await llm.generate(model="gemini-vision", system=None, turns=[])


async def test_the_recorded_storage_gives_back_what_was_uploaded() -> None:
    storage = RecordedStorage()
    assert storage.ready  # 설정이 비어 StorageError가 되지 않는다
    await storage.upload("u/poster/1.jpg", poster_bytes(), "image/jpeg")
    assert await storage.download("u/poster/1.jpg") == poster_bytes()
    await storage.remove("u/poster/1.jpg")
    assert storage.removed == ["u/poster/1.jpg"]
    with pytest.raises(StorageError):
        await storage.download("u/poster/1.jpg")


async def test_the_recorded_storage_signs_a_download_link_like_the_real_one() -> None:
    """문서함 받기(F-44)가 시나리오에서 돌 수 있게 서명 주소를 준다. 실제처럼 없는 파일은 서명할 때 거절이다."""
    storage = RecordedStorage()
    await storage.upload("u/lecture_material/f.pdf", b"%PDF-1.4", "application/pdf")
    url = await storage.signed_url("u/lecture_material/f.pdf", download_name="3주차 예제 & 답.pdf")
    assert url.startswith("recorded://storage/object/sign/uploads/u/lecture_material/f.pdf?token=")
    assert url.endswith("&download=3%EC%A3%BC%EC%B0%A8%20%EC%98%88%EC%A0%9C%20%26%20%EB%8B%B5.pdf")
    assert storage.signed == [("u/lecture_material/f.pdf", "3주차 예제 & 답.pdf", 300)]
    again = await storage.signed_url(
        "u/lecture_material/f.pdf", download_name="3주차 예제 & 답.pdf"
    )
    assert again != url  # 같은 파일·같은 이름이어도 부를 때마다 새 토큰이다(실제와 같다)
    await storage.signed_url("u/lecture_material/f.pdf", download_name="a.pdf", seconds=60)
    assert storage.signed[-1] == ("u/lecture_material/f.pdf", "a.pdf", 60)
    with pytest.raises(StorageMissing):
        await storage.signed_url("u/lecture_material/none.pdf", download_name="x.pdf")


async def test_the_recorded_calendar_keeps_one_event_per_number() -> None:
    calendar = RecordedCalendar()
    ends_at = datetime(2026, 11, 20, 18, tzinfo=KST)
    first = await calendar.insert("token", event_id="abc", title="[마감] 공고", ends_at=ends_at)
    assert isinstance(first, GoogleEvent)
    # 같은 번호로 또 넣으면 실제 Google처럼 409다(일정을 고치지 않는다)
    with pytest.raises(GoogleCalendarError) as conflict:
        await calendar.insert("token", event_id="abc", title="[마감] 공고", ends_at=ends_at)
    assert conflict.value.status == 409
    assert (calendar.inserts, len(calendar.events)) == (2, 1)  # 두 번 불러도 일정은 하나
    assert calendar.titles == {"abc": "[마감] 공고"}
    # 시각을 바꾸는 것은 move다(클라이언트가 409 뒤에 그렇게 한다)
    moved = await calendar.move(
        "token", event_id="abc", title="[마감] 공고", ends_at=ends_at + timedelta(days=1)
    )
    assert moved.ends_at == ends_at + timedelta(days=1)
    assert calendar.events["abc"].ends_at == ends_at + timedelta(days=1)
    assert await calendar.refresh("refresh-token") == ("recorded-access-token", 3600)
    await calendar.delete("token", "abc")
    assert calendar.events == {} and calendar.titles == {} and calendar.deletes == ["abc"]


def test_the_recorded_poster_answer_calls_the_submit_tool() -> None:
    turn = poster_submit(date(2026, 10, 12), confidence=0.42)
    assert [call.name for call in turn.tool_calls] == [SUBMIT]
    args = turn.tool_calls[0].args
    assert args["confidence"] == 0.42
    assert args["requirements"][0]["evidence_text"] in args["poster_text"]  # 근거가 원문에 있다
    # 날짜는 사진을 올린 날에서 센다. --now를 바꿔도 마감이 지난 포스터가 되지 않는다
    assert args["deadline"].startswith("2026-11-20")
    assert poster_submit(date(2027, 3, 5)).tool_calls[0].args["deadline"].startswith("2027-04-13")


def test_the_recorded_policy_number_is_not_a_real_one() -> None:
    """save_policy는 (출처, 번호)로 덮어쓰기다. 실제 번호면 수집해 둔 공고를 고치고 지운다."""
    assert not youth_policy()["plcyNo"].isdigit()
    assert "eval" in youth_policy()["plcyNo"]


def test_the_recorded_policy_is_nationwide_unless_a_region_is_given() -> None:
    assert youth_policy()["zipCd"] == nationwide()
    seoul = youth_policy(zipCd=sido_codes("서울특별시"))["zipCd"].split(",")
    assert len(seoul) == 25 and all(code.startswith("11") for code in seoul)
    with pytest.raises(AssertionError, match="모르는 시도"):
        sido_codes("서울시")


def test_the_poster_bytes_look_like_a_jpeg() -> None:
    from app.uploads import inspect_poster

    assert inspect_poster(poster_bytes()).type.mime == "image/jpeg"
    assert inspect_poster(poster_bytes()).sha256 != inspect_poster(poster_bytes(b"x")).sha256


def test_the_recorded_lms_moves_with_the_clock() -> None:
    """녹화한 과제의 마감은 **주입한 시계**에서 며칠 뒤다. 그래야 어느 날 돌려도 같은 결과가 나온다."""
    now = datetime(2026, 11, 3, 14, 20, tzinfo=KST)
    lms = RecordedLearningX(now)

    rows = {row["id"]: row for row in lms.assignment_rows[DB_COURSE_ID]}
    homework = rows[9_901_242]
    assert homework["due_at"] == lms_moment(now, 8)
    assert homework["due_at"].endswith("14:59:59Z")  # 그날 23:59:59 KST
    assert homework["submission"]["workflow_state"] == "unsubmitted"
    # 마감이 lock_at에만 있는 과제(녹화 17건 중 5건)와 이미 낸 과제도 한 벌에 있다
    assert rows[9_901_588]["due_at"] is None and rows[9_901_588]["lock_at"] == lms_moment(now, 6)
    assert rows[9_901_588]["submission"]["submitted_at"] == lms_moment(now, -1)


def test_the_recorded_lms_can_be_changed_between_syncs() -> None:
    """S16–S18은 전/후 녹화 두 벌 대신 한 벌을 고친다(과제 추가·마감 변경·제출)."""
    now = datetime(2026, 10, 12, 9, 0, tzinfo=KST)
    lms = RecordedLearningX(now)

    lms.add_assignment(DB_COURSE_ID, 9_901_900, "실습 4주차 결과 제출", in_days=12)
    added = next(row for row in lms.assignment_rows[DB_COURSE_ID] if row["id"] == 9_901_900)
    assert (added["name"], added["due_at"]) == ("실습 4주차 결과 제출", lms_moment(now, 12))

    lms.change_due(9_901_242, in_days=15)
    lms.submit(9_901_242, in_days=1)
    changed = next(row for row in lms.assignment_rows[DB_COURSE_ID] if row["id"] == 9_901_242)
    assert changed["due_at"] == lms_moment(now, 15)
    assert changed["submission"]["workflow_state"] == "submitted"
    assert changed["submission"]["submitted_at"] == lms_moment(now, 1)

    with pytest.raises(KeyError, match="녹화에 없는 과제"):
        lms.change_due(999, in_days=1)


@pytest.mark.anyio
async def test_the_recorded_lms_answers_like_the_client() -> None:
    """클라이언트 자리에 그대로 끼우는 가짜다(부른 경로를 적어 둔다)."""
    lms = RecordedLearningX(datetime(2026, 10, 12, 9, 0, tzinfo=KST))

    assert (await lms.me("token"))["id"] == LMS_USER_ID
    assert [course["id"] for course in await lms.courses("token")] == [DB_COURSE_ID, ML_COURSE_ID]
    assert len(await lms.assignments("token", ML_COURSE_ID)) == 1
    modules = await lms.modules("token", DB_COURSE_ID)
    assert [item["title"] for item in modules[0]["items"]] == ["3주차 강의"]
    assert await lms.module_items("token", DB_COURSE_ID, modules[0]["id"]) == modules[0]["items"]
    assert await lms.announcements("token", DB_COURSE_ID) == []  # 공지는 F-53이 채운다
    assert lms.calls[:3] == ["me", "courses", f"assignments:{ML_COURSE_ID}"]


def test_the_recorded_syllabus_pdf_still_reads() -> None:
    """S15가 쓰는 계획서 PDF는 담아 둔 이진 파일이다. 글자가 그대로 뽑히는지 여기서 본다.

    글꼴·압축이 들어간 파일이라 코드로 다시 만들 수 없어 zlib+base64로 담았다(app/eval/syllabus.py).
    pypdf가 올라가 글자가 달라지면 근거 문장 검사가 통째로 막히므로, 그때 이 테스트가 먼저 걸린다.
    """
    data = syllabus_pdf()
    inspected = inspect_syllabus(data)  # 올릴 수 있는 파일인지(쪽수·글자)
    assert inspected.page_count == 1
    squeezed = "".join(pdf_text(data).split())
    for line in (MIDTERM_LINE, PRESENTATION_LINE, FINAL_LINE):
        assert "".join(line.split()) in squeezed
    assert "".join(SYLLABUS_TEXT.split()) in squeezed


# S15가 쓰는 녹화 과목·계획서 날짜는 **주입 시계**에서 센다. 어느 날에 돌려도 같은 결과가 나오려면
# 그 셈이 모든 날에서 맞아야 해서, 학기 경계·방학·윤년을 골라 한 번에 본다
_CLOCKS = [
    "2026-01-01",  # 겨울 방학(지난 2학기는 일정 놓을 자리가 없다 → 다음 1학기)
    "2026-02-28",
    "2026-03-01",  # 1학기 첫날
    "2026-04-19",
    "2026-06-19",  # 1학기 중간고사 자리가 아직 남은 마지막 날 근처
    "2026-06-25",
    "2026-08-20",  # 여름 방학 → 다음 2학기
    "2026-09-01",  # 2학기 첫날
    "2026-10-12",  # DEFAULT_NOW
    "2026-12-31",
    "2027-01-15",
    "2028-02-29",  # 윤년
    "2031-09-30",
]


@pytest.mark.parametrize("day", _CLOCKS)
def test_the_recorded_semester_is_counted_from_the_clock(day: str) -> None:
    now = datetime.fromisoformat(f"{day}T09:00:00+09:00")
    today = now.astimezone(KST).date()
    start = semester_start(now)

    # 정규학기(3월·9월)만 센다 — 계절학기 과목에는 중간·기말이 없다
    assert (start.month, start.day) in ((3, 1), (9, 1))
    assert semester_code(now) == f"{start.year}{10 if start.month == 3 else 20}"

    for week in (MIDTERM_WEEK, PRESENTATION_WEEK, FINAL_WEEK):
        when = course_week(now, week)
        assert when == start + timedelta(weeks=week - 1)  # 주차는 학기 시작에서 센다
        assert when > today  # 아직 오지 않은 일정이어야 캘린더에 들어간다
        assert start <= when <= start + timedelta(days=SEMESTER_DAYS)  # 학기 범위 안이다

    # 녹화한 과목 행도 그 학기다(학기를 다른 칸에서 읽는 코드가 생겨도 틀리지 않게)
    course = RecordedLearningX(now).rows[0]
    assert course["name"].startswith(semester_code(now))
    assert course["term"]["name"] == f"{start.year}년 {1 if start.month == 3 else 2}학기"
    assert course["start_at"].startswith((start - timedelta(days=7)).isoformat()[:8])
