""".ics 내려받기(F-34): 파일 만들기와 `GET /calendar/ics`. 대상 조회는 test_calendar_api.py의 가짜 저장소를 쓴다."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.calendar.ics import IcsEvent, escape_text, event_uid, fold_line, render_calendar, utc_stamp
from app.clock import current_time
from app.config import Settings, get_settings
from app.eligibility import KST
from app.errors import ApiError
from app.main import create_app
from app.repositories.calendar import AssignmentDeadline, SyllabusDeadline, get_calendar_repo
from tests.conftest import make_token
from tests.test_calendar_api import (
    ASSIGNMENT_ID,
    DEADLINE,
    NOW,
    OPPORTUNITY_ID,
    SYLLABUS_ITEM_ID,
    FakeCalendarRepository,
)

ICS = "/api/v1/calendar/ics"
UNKNOWN_ID = "00000000-0000-4000-8000-0000000000ff"


def unfold(body: str) -> list[str]:
    """접은 줄을 다시 편다(RFC 5545 3.1). 확인할 때만 쓴다."""
    lines: list[str] = []
    for line in body.split("\r\n"):
        if line.startswith(" ") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def events_in(body: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for line in unfold(body):
        if line == "BEGIN:VEVENT":
            found.append({})
        elif found and ":" in line and line not in ("END:VEVENT", "END:VCALENDAR"):
            key, value = line.split(":", 1)
            found[-1].setdefault(key, value)
    return found


@pytest.fixture
def calendar(settings: Settings) -> FakeCalendarRepository:
    return FakeCalendarRepository(settings.token_encryption_key)


@pytest.fixture
def client(settings: Settings, calendar: FakeCalendarRepository) -> Iterator[TestClient]:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_calendar_repo] = lambda: calendar
    app.dependency_overrides[current_time] = lambda: NOW
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


# ---- 파일 만들기 ----


def test_text_is_escaped_and_long_lines_fold_between_characters() -> None:
    assert escape_text("a;b,c\\d\r\ne\nf") == r"a\;b\,c\\d\ne\nf"
    folded = fold_line("SUMMARY:" + "가" * 40)  # 8 + 120바이트
    pieces = folded.split("\r\n")
    assert len(pieces) == 2 and pieces[1].startswith(" ")
    assert all(len(piece.encode()) <= 75 for piece in pieces)
    assert "".join([pieces[0], pieces[1][1:]]) == "SUMMARY:" + "가" * 40  # 글자가 깨지지 않는다


def test_stamps_are_utc_and_naive_times_are_refused() -> None:
    assert utc_stamp(datetime(2026, 10, 24, 18, 0, tzinfo=KST)) == "20261024T090000Z"
    with pytest.raises(ValueError):
        utc_stamp(datetime(2026, 10, 24, 18, 0))


def test_render_orders_by_start_and_ends_lines_with_crlf() -> None:
    later = IcsEvent(event_uid("opportunity", "b"), "둘째", DEADLINE, DEADLINE + timedelta(hours=1))
    first = IcsEvent(event_uid("opportunity", "a"), "첫째", DEADLINE - timedelta(days=1), DEADLINE)
    body = render_calendar([later, first], now=NOW)
    assert body.endswith("END:VCALENDAR\r\n") and "\n" not in body.replace("\r\n", "")
    assert unfold(body)[:3] == [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//UNIPIVOT//UNIPIVOT Calendar//KO",
    ]
    found = events_in(body)
    assert [one["SUMMARY"] for one in found] == ["첫째", "둘째"]
    assert found[0]["UID"] == "opportunity-a@unipivot" and found[0]["DTSTAMP"] == "20261015T030000Z"


# ---- GET /calendar/ics ----


def test_ics_requires_login(client: TestClient) -> None:
    assert client.get(ICS, params={"opportunity_ids": OPPORTUNITY_ID}).status_code == 401


def test_the_file_holds_all_three_kinds_and_records_nothing(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """공고 마감·LMS 과제·계획서 일정이 Google에 넣을 때와 같은 시각·제목으로 들어간다."""
    res = client.get(
        ICS,
        params={
            "opportunity_ids": OPPORTUNITY_ID,
            "lms_assignment_ids": ASSIGNMENT_ID,
            "syllabus_item_ids": SYLLABUS_ITEM_ID,
        },
        headers=auth,
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "text/calendar; charset=utf-8"
    assert res.headers["content-disposition"] == 'attachment; filename="unipivot-20261015.ics"'
    found = {one["UID"]: one for one in events_in(res.text)}
    assert set(found) == {
        f"opportunity-{OPPORTUNITY_ID}@unipivot",
        f"lms_assignment-{ASSIGNMENT_ID}@unipivot",
        f"syllabus_item-{SYLLABUS_ITEM_ID}@unipivot",
    }
    deadline = found[f"opportunity-{OPPORTUNITY_ID}@unipivot"]
    assert deadline["SUMMARY"] == "[마감] 한양브레인 장학금"
    assert (deadline["DTSTART"], deadline["DTEND"]) == ("20261024T080000Z", "20261024T090000Z")
    assignment = found[f"lms_assignment-{ASSIGNMENT_ID}@unipivot"]
    assert assignment["SUMMARY"] == "[과제] 데이터베이스 · 실습 2주차 결과 제출"
    assert (assignment["DTSTART"], assignment["DTEND"]) == ("20261024T080000Z", "20261024T090000Z")
    exam = found[f"syllabus_item-{SYLLABUS_ITEM_ID}@unipivot"]
    assert exam["SUMMARY"] == "[시험] 데이터베이스 · 중간고사"
    assert (exam["DTSTART"], exam["DTEND"]) == ("20261024T090000Z", "20261024T100000Z")
    assert calendar.added == [] and calendar.events == {}  # 내려받기는 기록하지 않는다


def test_targets_that_cannot_go_in_are_skipped(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """없는 것·지난 것·마감 없는 것은 빠지고 나머지로 파일을 만든다."""
    calendar.assignment = AssignmentDeadline(
        ASSIGNMENT_ID, "지난 과제", "데이터베이스", NOW - timedelta(hours=1)
    )
    calendar.syllabus = SyllabusDeadline(
        SYLLABUS_ITEM_ID, "날짜 없는 일정", "데이터베이스", "exam", None
    )
    res = client.get(
        ICS,
        params={
            "opportunity_ids": f"{OPPORTUNITY_ID},{UNKNOWN_ID}",
            "lms_assignment_ids": ASSIGNMENT_ID,
            "syllabus_item_ids": SYLLABUS_ITEM_ID,
        },
        headers=auth,
    )
    assert res.status_code == 200
    assert [one["SUMMARY"] for one in events_in(res.text)] == ["[마감] 한양브레인 장학금"]


def test_nothing_left_is_404(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    calendar.opportunity = None  # 준비하지 않은 공고
    res = client.get(ICS, params={"opportunity_ids": OPPORTUNITY_ID}, headers=auth)
    assert res.status_code == 404
    assert res.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "내려받을 일정이 없어요.",
        "details": {},
    }


def test_the_same_id_twice_is_one_event(client: TestClient, auth: dict[str, str]) -> None:
    res = client.get(
        ICS, params={"opportunity_ids": f"{OPPORTUNITY_ID}, {OPPORTUNITY_ID},"}, headers=auth
    )
    assert res.status_code == 200 and len(events_in(res.text)) == 1


def test_the_filename_uses_the_kst_date(
    settings: Settings, calendar: FakeCalendarRepository, auth: dict[str, str]
) -> None:
    """UTC로는 아직 15일이어도 KST로 16일이면 16일 파일이다."""
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_calendar_repo] = lambda: calendar
    app.dependency_overrides[current_time] = lambda: datetime(2026, 10, 15, 16, 0, tzinfo=UTC)
    with TestClient(app) as late_client:
        res = late_client.get(ICS, params={"opportunity_ids": OPPORTUNITY_ID}, headers=auth)
    assert res.status_code == 200
    assert res.headers["content-disposition"] == 'attachment; filename="unipivot-20261016.ics"'


def test_other_errors_are_not_skipped(
    client: TestClient, auth: dict[str, str], calendar: FakeCalendarRepository
) -> None:
    """건너뛰는 건 넣을 수 없는 대상(404·409·422)뿐이다. DB가 없는 것 같은 오류는 그대로 올라간다."""

    async def unavailable(user_id: str, opportunity_id: str) -> None:
        raise ApiError(503, "DB_UNAVAILABLE", "잠시 후 다시 시도해 주세요.")

    calendar.prepared_opportunity = unavailable  # type: ignore[method-assign]
    res = client.get(ICS, params={"opportunity_ids": OPPORTUNITY_ID}, headers=auth)
    assert res.status_code == 503 and res.json()["error"]["code"] == "DB_UNAVAILABLE"


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"opportunity_ids": "abc"}, "opportunity_ids"),
        ({"lms_assignment_ids": f"{ASSIGNMENT_ID},x"}, "lms_assignment_ids"),
        ({"syllabus_item_ids": "1"}, "syllabus_item_ids"),
        ({}, "ids"),
        ({"opportunity_ids": ","}, "ids"),
    ],
)
def test_bad_or_missing_ids_are_422(
    client: TestClient, auth: dict[str, str], params: dict[str, str], field: str
) -> None:
    res = client.get(ICS, params=params, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_FAILED"
    assert list(res.json()["error"]["details"]["fields"]) == [field]


def test_too_many_ids_are_422(client: TestClient, auth: dict[str, str]) -> None:
    many = ",".join(f"00000000-0000-4000-8000-{index:012d}" for index in range(201))
    res = client.get(ICS, params={"opportunity_ids": many}, headers=auth)
    assert res.status_code == 422
    assert res.json()["error"]["details"]["fields"] == {"ids": "한 번에 200개까지 받을 수 있어요."}
    just_enough = ",".join(f"00000000-0000-4000-8000-{index:012d}" for index in range(200))
    assert client.get(ICS, params={"opportunity_ids": just_enough}, headers=auth).status_code == 404
