"""녹화한 응답(명세 12장 `fixtures: "recorded"`). 모델·파일 저장소·Google 캘린더를 대신한다.

시나리오 실행은 바깥 서비스를 부르지 않는다. 같은 입력에 같은 결과가 나와야 성공률·비용을 비교할 수
있고(PRD 8장 테스트 환경), 실제 계정에 일정이나 파일을 남기지 않는다. 캘린더는 테스트 계정 대신
메모리에 담고 시나리오가 끝나면 함께 버린다.

실제 호출로 바꿔 재는 것은 다음 일이다. 그때는 녹화 대신 진짜 클라이언트를 넣는다(fixtures 값을 늘린다).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.calendar.google import EVENT_MINUTES, GoogleCalendarClient, GoogleEvent
from app.llm import LlmReply, ModelTurn, ToolCall, ToolSpec, Turn, Usage, UserTurn
from app.posters.prompt import SUBMIT
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
        self.deletes: list[str] = []

    async def refresh(self, refresh_token: str) -> tuple[str, int]:
        return f"{RECORDED}-access-token", 3600

    async def insert(
        self, access_token: str, *, event_id: str, title: str, ends_at: datetime
    ) -> GoogleEvent:
        self.inserts += 1
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
