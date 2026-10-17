"""녹화한 응답(명세 12장 `fixtures: "recorded"`). 모델·파일 저장소·Google 캘린더를 대신한다.

시나리오 실행은 바깥 서비스를 부르지 않는다. 같은 입력에 같은 결과가 나와야 성공률·비용을 비교할 수
있고(PRD 8장 테스트 환경), 실제 계정에 일정이나 파일을 남기지 않는다. 캘린더는 테스트 계정 대신
메모리에 담고 시나리오가 끝나면 함께 버린다.

실제 호출로 바꿔 재는 것은 다음 일이다. 그때는 녹화 대신 진짜 클라이언트를 넣는다(fixtures 값을 늘린다).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from app.calendar.google import (
    EVENT_MINUTES,
    GoogleCalendarClient,
    GoogleCalendarError,
    GoogleEvent,
)
from app.llm import LlmReply, ModelTurn, ToolCall, ToolSpec, Turn, Usage, UserTurn
from app.lms.client import LearningXClient, LearningXError
from app.posters.prompt import SUBMIT
from app.syllabi.extract import SEMESTER_DAYS
from app.uploads.storage import StorageError, SupabaseStorage
from app.youth.regions import region_table

_KST = timezone(timedelta(hours=9), "KST")
RECORDED = "recorded"
# 녹화한 토큰 수. 단가표(app/pricing.py)로 비용이 되므로 시나리오마다 같아야 비용을 비교할 수 있다
RECORDED_USAGE = Usage(input_tokens=1200, output_tokens=240)
RECORDED_LATENCY_MS = 7


def tool_reply(name: str, **args: Any) -> ModelTurn:
    """도구 하나를 부르는 모델 답."""
    return ModelTurn(text=None, tool_calls=(ToolCall(name, args, id=f"{RECORDED}-{name}"),))


@dataclass
class Ask:
    """모델에 간 요청 하나. 시나리오가 무엇을 물었는지 확인할 때 쓴다."""

    model: str
    system: str | None
    turns: list[Turn]
    tools: list[str]
    force_tool: str | None

    @property
    def blobs(self) -> list[Any]:
        return [blob for turn in self.turns if isinstance(turn, UserTurn) for blob in turn.blobs]


Reply = ModelTurn | str | Callable[[Ask], ModelTurn | str]


class RecordedLlm:
    """녹화한 답을 차례로 돌려주는 모델. 답이 모자라면 시나리오가 실패한다."""

    provider = "google"

    def __init__(self, *replies: Reply, usage: Usage = RECORDED_USAGE) -> None:
        self.replies = list(replies)
        self.usage = usage
        self.asks: list[Ask] = []

    async def generate(
        self,
        *,
        model: str,
        system: str | None,
        turns: Sequence[Turn],
        tools: Sequence[ToolSpec] = (),
        thinking: str | None = None,
        max_output_tokens: int | None = None,
        force_tool: str | None = None,
    ) -> LlmReply:
        ask = Ask(model, system, list(turns), [tool.name for tool in tools], force_tool)
        self.asks.append(ask)
        if not self.replies:
            raise AssertionError(f"녹화한 답보다 모델을 더 많이 불렀어요(모델 {model})")
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(ask)
        turn = ModelTurn(text=reply) if isinstance(reply, str) else reply
        return LlmReply(
            turn=turn, usage=self.usage, latency_ms=RECORDED_LATENCY_MS, finish_reason="STOP"
        )


class RecordedStorage(SupabaseStorage):
    """메모리에 담는 파일 저장소. 올린 파일을 그대로 내려준다."""

    def __init__(self) -> None:
        super().__init__(base_url=f"{RECORDED}://storage", bucket="uploads", service_key=RECORDED)
        self.files: dict[str, bytes] = {}
        self.removed: list[str] = []

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        self.files[path] = data

    async def download(self, path: str) -> bytes:
        if path not in self.files:
            raise StorageError("파일 저장소에 그 파일이 없어요.")
        return self.files[path]

    async def remove(self, path: str) -> None:
        self.files.pop(path, None)
        self.removed.append(path)


class RecordedCalendar(GoogleCalendarClient):
    """메모리에 담는 Google 캘린더. 같은 번호로 또 넣어도 일정은 하나다(실제 Google은 409를 준다).

    실제 클라이언트처럼 **이번에 보낸** 시각으로 만든 일정을 돌려준다(app/calendar/google.py). 처음
    넣은 것을 돌려주면, 마감일이 바뀐 뒤 다시 등록할 때 시각이 안 바뀌는 버그를 가려 준다.
    """

    def __init__(self) -> None:
        super().__init__(
            api_base=f"{RECORDED}://google",
            token_url=f"{RECORDED}://google/token",
            client_id=RECORDED,
            client_secret=RECORDED,
        )
        self.events: dict[str, GoogleEvent] = {}
        self.titles: dict[str, str] = {}
        self.inserts = 0
        self.conflicts = 0  # 같은 번호로 또 넣은 횟수(409)
        self.moves = 0
        self.deletes: list[str] = []

    async def refresh(self, refresh_token: str) -> tuple[str, int]:
        return f"{RECORDED}-access-token", 3600

    async def insert(
        self, access_token: str, *, event_id: str, title: str, ends_at: datetime
    ) -> GoogleEvent:
        self.inserts += 1
        if event_id in self.events:
            # 실제 Google은 409를 주고 **일정을 고치지 않는다**. 클라이언트가 이어서 시각을 맞춘다
            self.conflicts += 1
            raise GoogleCalendarError("같은 번호가 이미 있어요", status=409)
        event = GoogleEvent(event_id, ends_at - timedelta(minutes=EVENT_MINUTES), ends_at)
        self.events[event_id] = event
        self.titles[event_id] = title
        return event

    async def move(
        self, access_token: str, *, event_id: str, title: str, ends_at: datetime
    ) -> GoogleEvent:
        """마감이 바뀐 일정의 시각을 고친다(F-51). 없는 일정이면 실제 Google처럼 404다."""
        if event_id not in self.events:
            raise GoogleCalendarError("없는 일정이에요", status=404)
        self.moves += 1
        event = GoogleEvent(event_id, ends_at - timedelta(minutes=EVENT_MINUTES), ends_at)
        self.events[event_id] = event
        self.titles[event_id] = title
        return event

    async def delete(self, access_token: str, event_id: str) -> None:
        self.events.pop(event_id, None)
        self.titles.pop(event_id, None)
        self.deletes.append(event_id)


# 녹화한 포스터 사진. 앞 바이트로 형식을 가리므로(app/uploads.sniff) JPEG 머리만 맞춘다
def poster_bytes(mark: bytes = b"eval-poster") -> bytes:
    return b"\xff\xd8\xff\xe0" + mark + b"\x00" * 600


# ── 녹화한 온통청년 정책 ─────────────────────────────────────────────────────
# 2026-10-13에 받은 실제 정책의 **칸 모양**이다(조건 없는 전국·상시 정책). 시나리오는 바꿀 칸만 넘긴다.
# plcyNo는 실제 번호를 쓰지 않는다 — save_policy는 (출처, 번호)로 덮어쓰기라서, 실제로 수집해 둔
# 정책의 번호를 넣으면 그 공고를 고치게 된다(app/eval/world.py의 youth가 한 번 더 막는다)
_POLICY: dict[str, Any] = {
    "plcyNo": "eval-recorded-policy",
    "plcyAprvSttsCd": "0044002",  # 승인
    "plcyNm": "청년 월세 한시 특별지원",
    "plcyKywdNm": None,
    "plcyExplnCn": "부모와 따로 사는 청년에게 월세 일부를 지원해요",
    "lclsfNm": "주거",
    "mclsfNm": "주택 및 주거공간",
    "plcySprtCn": "1. 월 최대 20만원\n2. 최대 12개월",
    "sprvsnInstCd": "1492000",
    "sprvsnInstCdNm": "국토교통부",
    "rgtrInstCdNm": "국토교통부",
    "aplyPrdSeCd": "0057002",  # 상시
    "aplyYmd": "",
    "bizPrdSeCd": "0056002",
    "bizPrdBgngYmd": "",
    "bizPrdEndYmd": "",
    "plcyAplyMthdCn": "복지로 누리집에서 신청",
    "srngMthdCn": "",
    "aplyUrlAddr": "https://www.bokjiro.go.kr",
    "sbmsnDcmntCn": "제출 서류: 1) 월세 지원 신청서\n2) 임대차계약서 사본",
    "etcMttrCn": "",
    "refUrlAddr1": "https://www.molit.go.kr",
    "refUrlAddr2": "",
    "sprtTrgtMinAge": "0",
    "sprtTrgtMaxAge": "0",
    "sprtTrgtAgeLmtYn": "N",
    "mrgSttsCd": "0055003",  # 제한없음
    "earnCndSeCd": "0043001",  # 소득 무관
    "earnMinAmt": "0",
    "earnMaxAmt": "0",
    "earnEtcCn": "",
    "addAplyQlfcCndCn": "",
    "ptcpPrpTrgtCn": "",
    "inqCnt": "47",
    "zipCd": "",  # 아래 youth_policy가 전국으로 채운다
    "plcyMajorCd": "0011009",  # 제한없음
    "jobCd": "0013010",  # 제한없음
    "schoolCd": "0049010",  # 제한없음
    "sbizCd": "0014010",  # 제한없음
    "frstRegDt": "2026-10-08 16:52:36",
    "lastMdfcnDt": "2026-10-08 17:06:23",
}


def nationwide() -> str:
    """전국: 지금 있는 끝 지역(구가 있는 시는 구) 전부. 온통청년의 전국 정책도 이 코드 목록이다."""
    return ",".join(sorted(region_table().leaves))


def sido_codes(sido: str) -> str:
    """시도 하나의 끝 지역 코드 전부. 그 시도에만 해당하는 정책을 만들 때 쓴다."""
    table = region_table()
    for prefix, leaves in table.by_sido.items():
        if table.names[min(leaves)].split()[0] == sido:
            return ",".join(sorted(leaves)) if prefix else ""
    raise AssertionError(f"모르는 시도: {sido}")


def youth_policy(**over: Any) -> dict[str, Any]:
    """녹화한 정책 하나. zipCd를 주지 않으면 전국이다."""
    return {**_POLICY, "zipCd": nationwide(), **over}


# ── 녹화한 포스터 읽기 답 ────────────────────────────────────────────────────
# 포스터에는 게시일이 없어서 모델은 "사진을 올린 날"을 기준으로 날짜를 읽는다(app/posters/prompt.py).
# 그래서 날짜는 주입한 시계에서 센다 — --now를 바꿔도 마감이 지난 포스터가 되지 않는다
APPLY_BEFORE_DAYS = 7  # 접수 시작은 올린 날보다 이만큼 앞
DEADLINE_AFTER_DAYS = 39  # 마감은 올린 날보다 이만큼 뒤
POSTER_TITLE = "2026 전국 대학생 SW 창업 아이디어톤"
_EVIDENCE = "참가 자격: 국내 대학 재학생 및 휴학생"


def poster_deadline(today: date) -> datetime:
    """녹화한 포스터의 마감 시각(KST 18:00)."""
    return datetime.combine(today + timedelta(days=DEADLINE_AFTER_DAYS), time(18, 0), tzinfo=_KST)


def poster_text(today: date) -> str:
    start, deadline = today - timedelta(days=APPLY_BEFORE_DAYS), poster_deadline(today)
    # 포스터에 흔한 "10. 5. ~ 11. 20." 모양. 0을 붙이지 않으려고 숫자를 직접 쓴다
    return (
        f"{POSTER_TITLE}\n"
        "주최: 과학기술정보통신부\n"
        f"{_EVIDENCE}\n"
        f"접수 기간: {start.year}. {start.month}. {start.day}."
        f" ~ {deadline.month}. {deadline.day}. 18:00\n"
        "제출 서류: 아이디어 제안서, 재학증명서"
    )


def poster_submit(today: date, **over: Any) -> ModelTurn:
    """포스터를 읽은 모델 답 하나(도구 submit_poster). 바꿀 칸만 넘긴다."""
    start, deadline = today - timedelta(days=APPLY_BEFORE_DAYS), poster_deadline(today)
    recorded: dict[str, Any] = {
        "poster_text": poster_text(today),
        "title": POSTER_TITLE,
        "organizer": "과학기술정보통신부",
        "category": "contest",
        "requirements": [
            {
                "clause_no": 1,
                "field": "enrollment_status",
                "operator": "in",
                "value_json": '["enrolled", "on_leave"]',
                "evidence_text": _EVIDENCE,
                "is_ambiguous": False,
            }
        ],
        "documents": [
            {"name": "아이디어 제안서", "is_required": True},
            {"name": "재학증명서", "is_required": True},
        ],
        "apply_start": start.isoformat(),
        "deadline": deadline.strftime("%Y-%m-%dT%H:%M"),
        "easy_summary": "국내 대학 재학생과 휴학생이 참가하는 창업 아이디어 대회예요.",
        "confidence": 0.88,
        "low_confidence_fields": [],
    }
    return tool_reply(SUBMIT, **{**recorded, **over})


# ── 녹화한 LearningX (F-50·F-51·F-52) ───────────────────────────────────────
# 2026-10-16에 학교 LMS에서 받은 응답의 **모양**이다(값은 바꿨다, tests/lms_samples.py와 같은 녹화).
# S16–S18은 "전/후 두 벌"이 필요해서, 한 벌을 두고 시나리오가 중간에 고친다(과제 추가·마감 변경·제출).

# 시나리오 전용 번호대다. 주차 항목·공지는 **과목 공통 표**라(ERD 3-2) 실제 과목 번호를 쓰면,
# 그 과목을 듣는 실제 사용자의 행과 섞이고 "처음 본 자료"가 0건이 되어 시나리오가 깨진다
LMS_USER_ID = 9_900_001
DB_COURSE_ID = 9_900_101
ML_COURSE_ID = 9_900_102


# 녹화한 계획서의 주차(app/eval/syllabus.py)를 날짜로 바꿀 때 쓰는 자리. 가장 늦은 일정이
# 기말고사 15주차이므로, 학기 시작에서 그만큼 지난 시계는 **다음 학기**를 보는 것으로 한다
_LAST_WEEK_DAYS = 14 * 7  # 15주차 = 시작 + 98일
_TERM_ROOM = _LAST_WEEK_DAYS - 50  # 8주차(시작 + 49일) 중간고사가 아직 오지 않은 자리


def semester_start(now: datetime) -> date:
    """녹화한 과목이 속한 학기의 시작일.

    계획서 일정을 읽는 기준이 **과목명에서 센 학기 시작일**이라(F-14), 과목명을 2026-2로 고정하면
    다른 날로 돌릴 때 학기 범위를 벗어난다. 시계에서 세어 어느 날에 돌려도 맞게 한다.

    정규학기(3월·9월)만 센다 — 계절학기 과목에는 중간·기말이 없고, 제품도 과목이 없을 때 3월·9월로
    끊는다(app/syllabi/extract.py의 semester_range). 학기가 이미 많이 지나 **중간고사를 놓을 자리가
    없으면** 다음 학기로 본다(계획서는 학기가 시작하기 전에 올리는 것이 보통이다).
    """
    today = now.astimezone(_KST).date()
    starts = sorted(
        date(year, month, 1)
        for year in (today.year - 1, today.year, today.year + 1)
        for month in (3, 9)
    )
    current = max(start for start in starts if start <= today)
    if (today - current).days <= _TERM_ROOM:
        return current
    return min(start for start in starts if start > today)


def semester_code(now: datetime) -> str:
    """그 학기의 과목명 앞자리(`202620`). 3월 학기는 10, 9월 학기는 20이다(ERD·포털과 같은 값)."""
    start = semester_start(now)
    return f"{start.year}{10 if start.month == 3 else 20}"


def course_week(now: datetime, week: int) -> date:
    """녹화한 계획서의 `N주차`가 가리키는 날(학기 시작 + (N-1)주). 모델이 세는 것과 같은 셈이다."""
    return semester_start(now) + timedelta(weeks=week - 1)


def lms_course(canvas_id: int, name: str, *, start: date) -> dict[str, Any]:
    """녹화한 과목 한 건. 과목명은 `202620HY23525_데이터베이스` 꼴이다.

    개강일·학기 이름도 과목명의 학기에서 센다. 고정해 두면 과목명은 2027-1인데 학기 이름은
    "2026년 2학기"인 세계가 되어, 학기를 다른 칸에서 읽는 코드가 생기면 조용히 틀린다.
    """
    opens = datetime.combine(start - timedelta(days=7), time(0, 0), tzinfo=_KST)
    closes = datetime.combine(start + timedelta(days=SEMESTER_DAYS), time(23, 59, 59), tzinfo=_KST)
    return {
        "id": canvas_id,
        "name": name,
        "course_code": name,
        "start_at": opens.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_at": closes.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "enrollment_term_id": 94,
        "term": {
            "id": 94,
            "name": f"{start.year}년 {1 if start.month == 3 else 2}학기",
            "end_at": None,
        },
        "time_zone": "Asia/Seoul",
        "workflow_state": "available",
        "enrollments": [
            {
                "type": "student",
                "role": "StudentEnrollment",
                "user_id": LMS_USER_ID,
                "enrollment_state": "active",
            }
        ],
    }


def lms_assignment(
    canvas_id: int,
    course_id: int,
    name: str,
    *,
    due_at: str | None,
    lock_at: str | None = None,
    state: str = "unsubmitted",
    submitted_at: str | None = None,
) -> dict[str, Any]:
    """녹화한 과제 한 건. 마감은 `due_at ?? lock_at`이고 시각은 모두 UTC(`...Z`)로 온다."""
    return {
        "id": canvas_id,
        "course_id": course_id,
        "name": name,
        "due_at": due_at,
        "lock_at": lock_at,
        "unlock_at": None,
        "points_possible": 0.0,
        "submission_types": ["online_upload"],
        "has_submitted_submissions": True,  # 과목 전체 기준이라 내 제출과 무관하다
        "is_quiz_assignment": False,
        "workflow_state": "published",
        "published": True,
        "html_url": f"https://lms.test/courses/{course_id}/assignments/{canvas_id}",
        "submission": {
            "id": 106_000_000 + canvas_id,
            "assignment_id": canvas_id,
            "user_id": LMS_USER_ID,
            "workflow_state": state,
            "submitted_at": submitted_at,
            "attempt": 1 if submitted_at else None,
            "score": None,
            "grade": None,
            "graded_at": None,
            "late": False,
            "missing": False,
            "excused": None,
        },
    }


def lms_moment(base: datetime, days: float) -> str:
    """시나리오 시계에서 며칠 뒤 **그날 23:59:59 KST**를 LMS가 주는 꼴(UTC `...Z`)로."""
    day = (base.astimezone(_KST) + timedelta(days=days)).date()
    at = datetime.combine(day, time(23, 59, 59), tzinfo=_KST)
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def lms_module(module_id: int, name: str, items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": module_id,
        "name": name,
        "position": 17,  # 연속이 아니다(1주차가 17인 과목이 있었다)
        "items_count": len(items),
        "state": "started",
        "items": list(items),
    }


def lms_item(item_id: int, title: str, kind: str = "ExternalTool") -> dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "type": kind,
        "position": 1,
        "indent": 0,
        "html_url": f"https://lms.test/courses/{DB_COURSE_ID}/modules/items/{item_id}",
        "url": f"https://lms.test/api/v1/courses/{DB_COURSE_ID}/module_items/{item_id}",
    }


class RecordedLearningX(LearningXClient):
    """메모리에 담은 LearningX. 바깥을 부르지 않고, 시나리오가 응답을 고쳐 "다음 주"를 만든다.

    S16은 과제를 더하고(`add_assignment`), S17은 마감을 바꾸고(`change_due`), S18은 제출로
    바꾼다(`submit`). 전/후 녹화 두 벌을 두는 대신 한 벌을 고치는 쪽이 무엇이 달라졌는지 분명하다.

    마감은 **주입한 시계에서 며칠 뒤**로 만든다(`lms_moment`). 그래서 시계를 어느 날로 두고 돌려도
    같은 결과가 나온다(PRD 8장: 같은 입력에 같은 결과).
    """

    def __init__(self, now: datetime) -> None:
        super().__init__(api_base=f"{RECORDED}://learningx")
        self.now = now
        self.rows = [
            lms_course(
                DB_COURSE_ID,
                f"{semester_code(now)}HY23525_데이터베이스",
                start=semester_start(now),
            ),
            lms_course(
                ML_COURSE_ID,
                f"{semester_code(now)}HY23534_기계학습",
                start=semester_start(now),
            ),
        ]
        # 연결할 때 이미 있던 과제들. 하나는 마감이 lock_at에만 있고, 둘은 이미 냈다
        self.assignment_rows: dict[int, list[dict[str, Any]]] = {
            DB_COURSE_ID: [
                lms_assignment(
                    9_901_242,
                    DB_COURSE_ID,
                    "실습 2주차 결과 제출",
                    due_at=lms_moment(now, 8),
                ),
                lms_assignment(
                    9_901_588,
                    DB_COURSE_ID,
                    "실습 3주차 결과 제출",
                    due_at=None,
                    lock_at=lms_moment(now, 6),
                    state="submitted",
                    submitted_at=lms_moment(now, -1),
                ),
            ],
            ML_COURSE_ID: [
                lms_assignment(
                    9_902_146,
                    ML_COURSE_ID,
                    "3주차 퀴즈",
                    due_at=lms_moment(now, -1),
                    state="graded",
                    submitted_at=lms_moment(now, -2),
                )
            ],
        }
        self.module_rows: dict[int, list[dict[str, Any]]] = {
            DB_COURSE_ID: [lms_module(9_903_837, "3주차", [lms_item(9_904_302, "3주차 강의")])],
            ML_COURSE_ID: [lms_module(9_903_894, "Week 3 : Trees", [])],
        }
        self.announcement_rows: dict[int, list[dict[str, Any]]] = {}
        self.calls: list[str] = []  # 부른 경로(시나리오가 "LMS를 다시 받았는지" 확인한다)

    # ── 시나리오가 쓰는 손잡이 ───────────────────────────────────────────────

    def add_assignment(self, course_id: int, canvas_id: int, name: str, *, in_days: float) -> None:
        """다음 동기화에서 새로 보일 과제. 마감은 시계에서 `in_days`일 뒤 23:59:59 KST다."""
        self.assignment_rows[course_id].append(
            lms_assignment(canvas_id, course_id, name, due_at=lms_moment(self.now, in_days))
        )

    def change_due(self, canvas_id: int, *, in_days: float) -> None:
        self._find(canvas_id)["due_at"] = lms_moment(self.now, in_days)

    def submit(self, canvas_id: int, *, in_days: float = 0) -> None:
        found = self._find(canvas_id)
        submitted_at = lms_moment(self.now, in_days)
        found["submission"] = {
            **found["submission"],
            "workflow_state": "submitted",
            "submitted_at": submitted_at,
            "attempt": 1,
            "submission_type": "online_upload",
        }

    def _find(self, canvas_id: int) -> dict[str, Any]:
        for rows in self.assignment_rows.values():
            for row in rows:
                if row["id"] == canvas_id:
                    return row
        raise KeyError(f"녹화에 없는 과제예요: {canvas_id}")

    # ── 클라이언트 흉내 ─────────────────────────────────────────────────────

    async def me(self, token: str) -> dict[str, Any]:
        self.calls.append("me")
        return {"id": LMS_USER_ID, "name": "테스트 학생", "short_name": "테스트 학생"}

    async def courses(self, token: str) -> list[dict[str, Any]]:
        self.calls.append("courses")
        return [dict(row) for row in self.rows]

    async def assignments(self, token: str, course_id: int) -> list[dict[str, Any]]:
        self.calls.append(f"assignments:{course_id}")
        return [dict(row) for row in self._rows(self.assignment_rows, course_id)]

    async def modules(self, token: str, course_id: int) -> list[dict[str, Any]]:
        self.calls.append(f"modules:{course_id}")
        return [dict(row) for row in self._rows(self.module_rows, course_id)]

    def _rows(self, table: dict[int, list[dict[str, Any]]], course_id: int) -> list[dict[str, Any]]:
        """녹화에 없는 과목은 실제 LMS처럼 404다(빈 목록이 아니다 — 그러면 "과목 실패"를 못 본다)."""
        if course_id not in table:
            raise LearningXError("없는 과목이에요", status=404)
        return table[course_id]

    async def module_items(
        self, token: str, course_id: int, module_id: int
    ) -> list[dict[str, Any]]:
        self.calls.append(f"module_items:{course_id}/{module_id}")
        for module in self.module_rows.get(course_id, []):
            if module["id"] == module_id:
                return [dict(item) for item in module["items"]]
        return []

    async def announcements(self, token: str, course_id: int) -> list[dict[str, Any]]:
        self.calls.append(f"announcements:{course_id}")
        return [dict(row) for row in self.announcement_rows.get(course_id, [])]
