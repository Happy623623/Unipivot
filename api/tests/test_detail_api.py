"""GET /opportunities/{id} 공고 상세(S1-6). 저장소는 가짜다. SQL과 판정은 test_detail_db.py가 본다."""

from datetime import date, datetime

from fastapi.testclient import TestClient

from app.eligibility import KST
from app.schemas.opportunities import (
    AttachmentItem,
    Clause,
    Condition,
    DetailEligibility,
    DocumentItem,
    OpportunityDetail,
    Prep,
    Process,
    ProcessStep,
)
from tests.conftest import USER_ID
from tests.fakes import FakeOpportunityRepository

OPPORTUNITY_ID = "00000000-0000-4000-8000-0000000000aa"
DETAIL = OpportunityDetail(
    id=OPPORTUNITY_ID,
    title="2026-2 한양브레인 장학금",
    organizer="학생지원팀",
    category="scholarship",
    source_type="school_notice",
    status="active",
    original_url="https://www.hanyang.ac.kr/notice/url/1d396",
    poster_url=None,
    easy_summary="직전학기 성적이 좋은 학생에게 등록금 일부를 감면해 줘요.",
    apply_start_at=None,
    deadline_at=datetime(2026, 10, 15, 23, 59, tzinfo=KST),
    needs_review=False,
    extraction_confidence=0.92,
    uploaded_by_me=False,
    course_name=None,
    attachments=[
        AttachmentItem(
            id="00000000-0000-4000-8000-0000000000b1",
            file_name="2026-2 장학 안내.hwp",
            source_url="https://www.hanyang.ac.kr/download/1",
            extract_status="succeeded",
        )
    ],
    eligibility=DetailEligibility(
        status="undetermined",
        display_status="missing_info",
        reason_text="직전학기 이수학점 입력 필요",
        basis_date=date(2026, 10, 15),
        requirements_version=1,
        missing_fields=["credits_last_semester"],
        clauses=[Clause(clause_no=1, outcome="unknown", condition_count=1)],
        conditions=[
            Condition(
                requirement_id="00000000-0000-4000-8000-0000000000c1",
                clause_no=1,
                field="credits_last_semester",
                label="직전학기 이수학점",
                operator="gte",
                value=12,
                user_value=None,
                condition_text="12학점 이상",
                user_value_text=None,
                outcome="unknown",
                unknown_reason="missing_profile",
                evidence_text="직전학기 12학점 이상 취득한 재학생",
                is_ambiguous=False,
            )
        ],
        evaluated_at=datetime(2026, 10, 10, 9, 0, tzinfo=KST),
    ),
    documents=[
        DocumentItem(
            id="00000000-0000-4000-8000-0000000000d1",
            name="장학금 신청서",
            issuer=None,
            how_to=None,
            lead_days=None,
            effort_minutes=None,
            form_url=None,
            is_required=True,
            task_id=None,
            is_done=None,
        )
    ],
    prep=Prep(prepared=False, prep_plan_id=None, tasks_total=0, tasks_done=0, calendar_events=[]),
    process=Process(
        extraction=[
            ProcessStep(
                seq=1,
                tool="read_attachment_text",
                label="첨부 '2026-2 장학 안내.hwp' 읽기",
                status="succeeded",
                latency_ms=900,
                chosen_by="agent",
                note="본문에 '첨부 참조'만 있어 첨부를 읽음",
            )
        ],
        evaluated_at=datetime(2026, 10, 10, 9, 0, tzinfo=KST),
        prepare_run_id=None,
    ),
    reported_by_me=False,
)


def test_detail_requires_login(client: TestClient) -> None:
    assert client.get(f"/api/v1/opportunities/{OPPORTUNITY_ID}").status_code == 401


def test_detail_returns_the_judgment_table(
    client: TestClient, auth: dict[str, str], feed: FakeOpportunityRepository
) -> None:
    feed.details[OPPORTUNITY_ID] = DETAIL
    res = client.get(f"/api/v1/opportunities/{OPPORTUNITY_ID.upper()}", headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert feed.detail_calls == [
        (USER_ID, OPPORTUNITY_ID, "테스트 학생")
    ]  # id는 소문자로 바꿔 넘긴다
    assert body["deadline_at"] == "2026-10-15T23:59:00+09:00"
    assert body["eligibility"]["basis_date"] == "2026-10-15"
    assert body["eligibility"]["conditions"][0]["unknown_reason"] == "missing_profile"
    assert body["process"]["extraction"][0]["chosen_by"] == "agent"
    assert set(body) == {  # API 명세 v0.4 5장 · web OpportunityDetail
        "id",
        "title",
        "organizer",
        "category",
        "source_type",
        "status",
        "original_url",
        "poster_url",
        "easy_summary",
        "apply_start_at",
        "deadline_at",
        "needs_review",
        "extraction_confidence",
        "uploaded_by_me",
        "course_name",
        "attachments",
        "eligibility",
        "documents",
        "prep",
        "process",
        "reported_by_me",
    }


def test_detail_not_found_and_bad_id(client: TestClient, auth: dict[str, str]) -> None:
    res = client.get(f"/api/v1/opportunities/{OPPORTUNITY_ID}", headers=auth)
    assert res.status_code == 404 and res.json()["error"]["code"] == "NOT_FOUND"
    res = client.get("/api/v1/opportunities/not-a-uuid", headers=auth)
    assert res.status_code == 422
    assert "opportunity_id" in res.json()["error"]["details"]["fields"]
