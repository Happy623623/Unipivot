"""원문 확인 필요 이유 코드(오케스트레이션 명세 v1 3.3, O2).

학생에게 보이는 이유(review_reasons)는 쉬운 말 한 문장이라 기계가 세기 어렵다. 그래서 같은 이유에 코드를
하나씩 붙인다. 화면 문구는 그대로이고, 코드는 실행 기록(agent_runs.review_codes)에만 남는다 — 엔진별
지표·평가(O3)가 세고, 캐스케이드(O4)가 위 등급 모델로 올릴지 정할 때 본다.

| 코드 | 지금 문구 | 원인 |
| NO_SUBMISSION | 자격 요건을 정리하지 못함 | 모델 |
| REPAIRED | (마지막 제출에서 코드가 고친 것들) | 모델 |
| LOW_CONFIDENCE | AI가 정리한 조건을 확신하지 못함 | 모델 |
| NOT_READ | 첨부를 읽지 않고 자격 제한이 없다고 봄 | 모델 |
| READ_CAP | 읽기 횟수 한도에 닿아 … | 상한 |
| TOKEN_CAP | 처리 분량 한도에 닿아 … | 상한 |
| MODEL_FLAG | AI 메모: … / AI가 원문 확인이 필요하다고 표시함 | 원문 |
| AMBIGUOUS | 자동으로 판정할 수 없는 조건이 있음 | 원문 |
| UNREADABLE | 읽지 못한 첨부가 있음 | 파일 |
| PARTIAL_READ | (일부만 읽은 본문·첨부) | 상한·파일 |
| MISSING_FILE | 가져오지 못해 읽지 않은 첨부: … | 수집 |
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class ReviewCode(StrEnum):
    NO_SUBMISSION = "NO_SUBMISSION"
    REPAIRED = "REPAIRED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NOT_READ = "NOT_READ"
    READ_CAP = "READ_CAP"
    TOKEN_CAP = "TOKEN_CAP"
    MODEL_FLAG = "MODEL_FLAG"
    AMBIGUOUS = "AMBIGUOUS"
    UNREADABLE = "UNREADABLE"
    PARTIAL_READ = "PARTIAL_READ"
    MISSING_FILE = "MISSING_FILE"


@dataclass(frozen=True)
class ReviewReason:
    code: ReviewCode  # 기계가 세는 이유
    text: str  # 학생에게 보이는 쉬운 말(review_reasons 문자열 그대로)


def review_texts(reasons: Iterable[ReviewReason]) -> tuple[str, ...]:
    """화면에 보일 이유. 같은 문구는 한 번만, 처음 나온 순서대로(지금 review_reasons와 같다)."""
    return tuple(dict.fromkeys(reason.text for reason in reasons))


def review_codes(reasons: Iterable[ReviewReason]) -> tuple[str, ...]:
    """실행 기록에 남길 코드. 같은 코드는 한 번만, 처음 나온 순서대로.

    한 실행에 첨부 셋을 일부만 읽어도 PARTIAL_READ는 하나다 — 지표는 "이 이유가 나온 실행 수"를 센다.
    """
    return tuple(dict.fromkeys(str(reason.code) for reason in reasons))
