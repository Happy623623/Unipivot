"""내부 서류 사전(PRD 6장 get_document_guide). 자주 내는 서류의 발급처·방법·소요 일수다.

사전에 있는 서류는 모델을 부르지 않는다. 없는 서류만 모델에 묻는다(app/prepare/guide.py).
lead_days는 발급(또는 준비)까지 걸리는 일수이고 0이면 바로 받는다. effort_minutes는 직접 쓰는 데 드는
시간으로 화면에만 보인다(역산에는 쓰지 않는다, ERD 5장). 학교 증명서는 ERICA 학부생 기준이다.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Guide:
    issuer: str | None
    how_to: str | None
    lead_days: int | None
    effort_minutes: int | None = None


@dataclass(frozen=True)
class _Entry:
    keys: tuple[str, ...]  # 이름(normalize)에 들어 있으면 이 서류로 본다
    guide: Guide
    excludes: tuple[str, ...] = ()  # 이름에 이 말이 있으면 이 서류가 아니다


_SCHOOL = "한양인 포털"
_SCHOOL_HOW = "한양인 포털 증명서 발급 메뉴나 교내 무인 발급기에서 바로 발급"
_GOV24 = "정부24"
_GOV24_HOW = "정부24에서 발급하거나 가까운 주민센터 무인 발급기에서 발급"

# 위에서부터 맞춰 본다. 좁은 이름(사업자등록증명)을 넓은 이름(신청서)보다 먼저 둔다
_ENTRIES: tuple[_Entry, ...] = (
    _Entry(  # 어학 성적표는 학교 성적표보다 먼저 본다
        ("토익", "toeic", "토플", "toefl", "오픽", "opic", "텝스", "teps", "어학성적"),
        Guide("시험 기관", "시험 기관 누리집에서 성적표를 출력", 0),
    ),
    _Entry(("재학증명서",), Guide(_SCHOOL, _SCHOOL_HOW, 0)),
    _Entry(("성적증명서", "성적표"), Guide(_SCHOOL, _SCHOOL_HOW, 0)),
    _Entry(("졸업예정증명서", "졸업증명서"), Guide(_SCHOOL, _SCHOOL_HOW, 0)),
    _Entry(("휴학증명서", "재적증명서", "수료증명서"), Guide(_SCHOOL, _SCHOOL_HOW, 0)),
    _Entry(("주민등록등본", "주민등록초본", "주민등록표"), Guide(_GOV24, _GOV24_HOW, 0)),
    _Entry(
        ("가족관계증명서", "기본증명서"),
        Guide(
            "대법원 전자가족관계등록시스템", "전자가족관계등록시스템이나 정부24에서 바로 발급", 0
        ),
    ),
    _Entry(
        ("자격득실",),
        Guide("국민건강보험공단", "건강보험공단 누리집이나 The건강보험 앱에서 바로 발급", 0),
    ),
    _Entry(
        ("보험료납부확인서", "보험료납입확인서"),
        Guide("국민건강보험공단", "건강보험공단 누리집이나 The건강보험 앱에서 바로 발급", 0),
    ),
    _Entry(("소득금액증명",), Guide("국세청 홈택스", "홈택스나 손택스 앱에서 바로 발급", 0)),
    _Entry(("사업자등록증명",), Guide("국세청 홈택스", "홈택스나 손택스 앱에서 바로 발급", 0)),
    _Entry(("수급자증명서", "수급자확인서"), Guide(_GOV24, _GOV24_HOW, 0)),
    _Entry(("차상위",), Guide(_GOV24, _GOV24_HOW, 0)),
    _Entry(("한부모가족증명서",), Guide(_GOV24, _GOV24_HOW, 0)),
    _Entry(("장애인증명서",), Guide(_GOV24, _GOV24_HOW, 0)),
    _Entry(("병적증명서",), Guide("병무청", "병무청 누리집에서 바로 발급", 0)),
    _Entry(
        ("통장사본",), Guide("본인 은행", "은행 앱에서 통장 사본을 내려받거나 통장 표지를 찍기", 0)
    ),
    _Entry(("신분증사본",), Guide("본인", "주민등록증이나 운전면허증 앞면을 찍거나 스캔", 0)),
    _Entry(
        ("임대차계약서",),
        Guide("본인(계약서)", "가지고 있는 임대차계약서를 스캔하거나 사본을 준비", 0),
    ),
    _Entry(("재직증명서",), Guide("다니는 회사", "회사 인사 담당자에게 발급 요청", 1)),
    _Entry(("추천서",), Guide("지도교수", "교수님께 미리 요청해 받기", 7, 30)),
    _Entry(("자기소개서", "자소서"), Guide("직접 작성", "공고의 문항에 맞춰 직접 작성", 2, 120)),
    _Entry(
        ("사업계획서",),
        Guide("직접 작성", "공고의 양식에 맞춰 사업 내용과 계획을 직접 작성", 5, 240),
    ),
    _Entry(
        ("학업계획서", "활동계획서", "연구계획서", "수학계획서"),
        Guide("직접 작성", "공고의 양식에 맞춰 직접 작성", 2, 120),
        excludes=("강의계획서",),
    ),
    _Entry(("포트폴리오",), Guide("직접 작성", "그동안의 작업과 활동을 모아 정리", 3, 180)),
    _Entry(
        ("동의서",),
        Guide("공고 첨부 양식", "공고에 붙은 양식을 내려받아 서명", 0, 10),
    ),
    _Entry(
        ("신청서", "지원서"),
        Guide("공고 첨부 양식·신청 사이트", "공고에 붙은 양식이나 신청 사이트에서 작성", 0, 30),
    ),
)

_BRACKETS = re.compile(r"[(\[{（［【][^)\]}）］】]*[)\]}）］】]")
_SPACES = re.compile(r"[\s·ㆍ・_\-]+")


def normalize(name: str) -> str:
    """괄호 안(발급 기한·부수)과 공백·가운뎃점을 지우고 영문은 소문자로 바꾼다."""
    return _SPACES.sub("", _BRACKETS.sub("", name)).lower()


def lookup(name: str) -> Guide | None:
    """사전에 있는 서류면 안내, 없으면 None."""
    key = normalize(name)
    for entry in _ENTRIES:
        if any(word in key for word in entry.keys) and not any(
            word in key for word in entry.excludes
        ):
            return entry.guide
    return None
