"""준비하기 규칙(F-30·F-31): 서류 사전, 역산 일정, 청년정책 제출 서류 칸. DB·모델 없이 돈다."""

from datetime import date

import pytest

from app.prepare import guide
from app.prepare.documents import lookup, normalize
from app.prepare.plan import PlanDocument, build_tasks
from app.repositories.prepare import STALE_AFTER_SECONDS
from app.youth.convert import raw_section


def test_the_guide_call_is_cut_off_before_a_run_looks_stuck() -> None:
    """모델 호출 상한이 멈춤 기준보다 길면, 아직 도는 실행을 다음 누름이 멈춘 것으로 보고 지운다."""
    assert guide.TIMEOUT_SECONDS < STALE_AFTER_SECONDS


def test_build_tasks_counts_back_from_the_deadline() -> None:
    """서류는 마감 2일 전 − 소요 일수, 신청 제출은 마감 1일 전. 소요 일수를 모르면 하루다."""
    documents = [
        PlanDocument("d1", "재학증명서", 0),
        PlanDocument("d2", "추천서", 7),
        PlanDocument("d3", "참가 확인서", None),
    ]
    tasks = build_tasks(documents, date(2026, 10, 15), date(2026, 10, 5))
    assert [(t.title, t.due_date, t.document_id, t.sort_order) for t in tasks] == [
        ("재학증명서 준비", date(2026, 10, 13), "d1", 0),
        ("추천서 준비", date(2026, 10, 6), "d2", 1),
        ("참가 확인서 준비", date(2026, 10, 12), "d3", 2),
        ("신청 제출", date(2026, 10, 14), None, 3),
    ]


def test_build_tasks_never_goes_before_today() -> None:
    documents = [PlanDocument("d1", "추천서", 7), PlanDocument("d2", "재학증명서", 0)]
    tasks = build_tasks(documents, date(2026, 10, 6), date(2026, 10, 5))
    assert [t.due_date for t in tasks] == [date(2026, 10, 5)] * 3
    same_day = build_tasks(documents, date(2026, 10, 5), date(2026, 10, 5))  # 오늘 마감
    assert {t.due_date for t in same_day} == {date(2026, 10, 5)}


def test_build_tasks_without_documents_is_one_submission() -> None:
    """서류가 없는 공고는 신청 제출 하나다(서류 수 0 = 서류 할 일 0)."""
    tasks = build_tasks([], date(2026, 10, 20), date(2026, 10, 5))
    assert [(t.title, t.due_date, t.document_id) for t in tasks] == [
        ("신청 제출", date(2026, 10, 19), None)
    ]


@pytest.mark.parametrize(
    ("name", "issuer", "lead_days"),
    [
        ("재학증명서(최근 1개월 이내 발급분) 1부", "한양인 포털", 0),
        ("성적증명서", "한양인 포털", 0),
        ("TOEIC 성적표", "시험 기관", 0),  # 학교 성적표보다 먼저 본다
        ("주민등록표 등본", "정부24", 0),
        ("가족관계증명서(상세)", "대법원 전자가족관계등록시스템", 0),
        ("건강보험 자격득실 확인서", "국민건강보험공단", 0),
        ("기초생활수급자 증명서", "정부24", 0),
        ("통장 사본", "본인 은행", 0),
        ("교수 추천서", "지도교수", 7),
        ("활동계획서", "직접 작성", 2),
        ("사업계획서", "직접 작성", 5),
        ("개인정보 수집·이용 동의서", "공고 첨부 양식", 0),
        ("장학금 신청서", "공고 첨부 양식·신청 사이트", 0),
    ],
)
def test_dictionary_knows_common_documents(name: str, issuer: str, lead_days: int) -> None:
    guide = lookup(name)
    assert guide is not None and (guide.issuer, guide.lead_days) == (issuer, lead_days)
    assert guide.how_to


def test_dictionary_leaves_unknown_documents_to_the_model() -> None:
    assert lookup("참가 확인서") is None
    assert lookup("강의계획서") is None  # 계획서지만 학생이 쓰는 서류가 아니다
    assert normalize("재학 증명서 (1부)") == "재학증명서"
    assert normalize("TOEIC·성적표") == "toeic성적표"


def test_raw_section_reads_one_youth_field() -> None:
    raw = (
        "정책 설명: 청년 월세 지원\n"
        "제출 서류: 1) 신청서\n2) 주민등록등본\n* 해당자만 소득 증빙\n"
        "신청 사이트: www.example.go.kr\n"
        "기타: 문의는 주민센터"
    )
    assert raw_section(raw, "제출 서류") == "1) 신청서\n2) 주민등록등본\n* 해당자만 소득 증빙"
    assert raw_section(raw, "기타") == "문의는 주민센터"
    assert raw_section(raw, "심사 방법") is None
    assert raw_section(None, "제출 서류") is None
