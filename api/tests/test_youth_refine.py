"""청년정책 서술형 자격 요건화(F-11b, app/youth/refine.py) — 모델 답을 코드가 다시 보는 부분과 합치기, 판정까지.

모델은 가짜(ScriptedLlm)다. DB 없이 돈다. 수집에 붙여 저장하는 것은 tests/test_youth_refine_db.py가 본다.
"""

from datetime import date
from typing import Any

import pytest

from app.config import Settings
from app.eligibility import Profile, Requirement, check_eligibility
from app.extraction.models import RequirementDraft
from app.youth.convert import PolicyRecord, convert
from app.youth.refine import (
    COVERAGE,
    SUBMIT,
    Found,
    check,
    coverage,
    extract,
    merge,
    refined_hash,
    system_prompt,
    wanted,
    youth_refiner,
)
from app.youth.regions import region_table
from tests.llm_fakes import ScriptedLlm, call
from tests.youth_samples import policy

pytestmark = pytest.mark.anyio

TODAY = date(2026, 11, 28)
EXTRA = "만 19세 이상 34세 이하 미취업 청년"
LIMIT = "대학 재학생 및 휴학생 제외"


def item(source: str, field: str, operator: str, value: str, evidence: str, clause: int = 1):
    return {
        "source": source,
        "clause_no": clause,
        "field": field,
        "operator": operator,
        "value_json": value,
        "evidence_text": evidence,
    }


def record(**values: Any) -> PolicyRecord:
    converted = convert(policy(**values), TODAY, region_table())
    assert isinstance(converted, PolicyRecord)
    return converted


def texts_of(converted: PolicyRecord) -> list[str]:
    return [
        draft.value.get("text", "") for draft in converted.requirements if draft.field == "other"
    ]


# ── 보낼 글 ──────────────────────────────────────────────────────────────────


def test_only_meaningful_free_text_is_sent() -> None:
    assert wanted(policy(addAplyQlfcCndCn=EXTRA, ptcpPrpTrgtCn="-")) == {"추가 자격": EXTRA}
    assert wanted(policy(addAplyQlfcCndCn="해당없음", ptcpPrpTrgtCn="")) == {}
    assert wanted(policy(addAplyQlfcCndCn="a\n  b", ptcpPrpTrgtCn=LIMIT)) == {
        "추가 자격": "a b",
        "참여 제한": LIMIT,
    }


def test_the_prompt_turns_exclusions_around_and_lists_job_values() -> None:
    prompt = system_prompt()
    assert "참여 제한" in prompt and "not_in" in prompt and SUBMIT in prompt
    assert "unemployed" in prompt and "founder" in prompt  # job_status 값(온통청년 jobCd와 같다)
    assert "other(" not in prompt  # 기타 조건은 모델이 내지 않는다(그 글은 원문 확인으로 둔다)


# ── 코드가 다시 보기 ─────────────────────────────────────────────────────────


def test_conditions_need_their_evidence_in_the_text() -> None:
    texts = {"추가 자격": EXTRA}
    found = check(
        {
            "conditions": [
                item(
                    "추가 자격",
                    "age",
                    "between",
                    '{"min": 19, "max": 34}',
                    "만 19세 이상 34세 이하",
                ),
                item("추가 자격", "job_status", "in", '["unemployed"]', "미취업 청년"),
                {  # 모양은 맞지만 근거가 글에 없다(지어낸 조건)
                    **item("추가 자격", "region", "in", '["서울특별시"]', "서울 거주"),
                    "basis": "unspecified",
                },
            ],
            "covered": ["추가 자격"],
        },
        texts,
    )
    assert [(source, draft.field) for source, _, draft in found.conditions] == [
        ("추가 자격", "age"),
        ("추가 자격", "job_status"),
    ]
    # 지어낸 조건을 버렸으니 "다 옮겼다"를 믿지 않는다 — 기타 조건(원문 확인)이 남는다
    assert (found.dropped, found.covered) == (1, ())


def test_spacing_and_punctuation_do_not_matter_for_evidence() -> None:
    texts = {"추가 자격": "- 만19세~34세\n- 미취업자(구직자 포함)"}
    found = check(
        {
            "conditions": [
                item("추가 자격", "age", "between", '{"min": 19, "max": 34}', "만 19세 ~ 34세"),
                item("추가 자격", "job_status", "in", '["unemployed"]', "미취업자 (구직자 포함)"),
            ],
            "covered": ["추가 자격"],
        },
        texts,
    )
    assert len(found.conditions) == 2 and found.covered == ("추가 자격",)


def test_shapes_the_engine_cannot_take_are_dropped() -> None:
    texts = {"추가 자격": EXTRA}
    for bad in (
        item("추가 자격", "age", "in", "[19]", "만 19세 이상"),  # 나이에 in은 없다
        item("추가 자격", "age", "gte", "not json", "만 19세 이상"),
        item("추가 자격", "other", "eq", '{"text": "x"}', "만 19세 이상"),  # 기타는 받지 않는다
        item("추가 자격", "region", "in", '["중구"]', "만 19세 이상"),  # 시도 없는 지역
        item("참여 제한", "age", "gte", "19", "만 19세 이상"),  # 보내지 않은 글
        "문자열",
    ):
        found = check({"conditions": [bad], "covered": ["추가 자격"]}, texts)
        assert found.conditions == () and found.dropped == 1 and found.covered == (), bad


def test_a_text_counts_as_covered_only_when_most_of_it_is_cited() -> None:
    texts = {"추가 자격": EXTRA + ", 자립준비청년은 별도 문의"}
    found = check(
        {
            "conditions": [
                item(
                    "추가 자격",
                    "age",
                    "between",
                    '{"min": 19, "max": 34}',
                    "만 19세 이상 34세 이하",
                )
            ],
            "covered": ["추가 자격"],  # 모델은 다 옮겼다고 했지만 근거가 글의 절반도 안 된다
        },
        texts,
    )
    assert coverage(texts["추가 자격"], ["만 19세 이상 34세 이하"]) < COVERAGE
    assert found.covered == () and len(found.conditions) == 1


def test_coverage_counts_overlaps_once() -> None:
    assert coverage("abc def", ["abc", "abc", "def"]) == 1.0
    assert coverage("abcdef", ["abc", "abc"]) == 0.5  # 같은 곳을 두 번 인용해도 절반이다
    assert coverage("abcd", ["ab"]) == 0.5
    assert coverage("", ["x"]) == 0.0


# ── 합치기와 판정 ────────────────────────────────────────────────────────────


def test_a_covered_text_replaces_its_review_condition() -> None:
    converted = record(addAplyQlfcCndCn=EXTRA, ptcpPrpTrgtCn=LIMIT, jobCd="0013010")
    assert texts_of(converted) == [f"추가 자격: {EXTRA}", f"참여 제한: {LIMIT}"]
    found = check(
        {
            "conditions": [
                item(
                    "추가 자격",
                    "age",
                    "between",
                    '{"min": 19, "max": 34}',
                    "만 19세 이상 34세 이하",
                ),
                item("추가 자격", "job_status", "in", '["unemployed"]', "미취업 청년", clause=2),
                item(
                    "참여 제한",
                    "enrollment_status",
                    "not_in",
                    '["enrolled", "on_leave"]',
                    "대학 재학생 및 휴학생 제외",
                ),
            ],
            "covered": ["추가 자격"],  # 참여 제한은 다 옮겼다고 하지 않았다
        },
        {"추가 자격": EXTRA, "참여 제한": LIMIT},
    )

    merged = merge(converted, found, {"추가 자격": EXTRA, "참여 제한": LIMIT})

    assert texts_of(merged) == [f"참여 제한: {LIMIT}"]  # 다 옮긴 글의 기타 조건만 빠진다
    assert [(d.clause_no, d.field, d.operator) for d in merged.requirements] == [
        (1, "other", "eq"),
        (2, "age", "between"),
        (3, "job_status", "in"),
        (4, "enrollment_status", "not_in"),
    ]
    assert merged.content_hash == converted.content_hash  # 해시는 부르는 쪽(YouthRefiner)이 정한다


def test_same_clause_numbers_in_one_text_are_one_or_group() -> None:
    converted = record(addAplyQlfcCndCn="미취업자 또는 프리랜서")
    found = Found(
        conditions=(
            ("추가 자격", 1, _draft("job_status", "in", ["unemployed"])),
            ("추가 자격", 1, _draft("job_status", "in", ["freelancer"])),
        ),
        covered=("추가 자격",),
        dropped=0,
        submitted=True,
    )
    merged = merge(converted, found, {"추가 자격": "미취업자 또는 프리랜서"})
    assert [(d.clause_no, d.value) for d in merged.requirements] == [
        (1, ["unemployed"]),
        (1, ["freelancer"]),
    ]


def test_the_judgment_fails_who_clearly_does_not_fit_and_keeps_review_for_the_rest() -> None:
    """옮긴 조건에 확실히 맞지 않는 학생은 지원 어려움이 된다. 남은 글이 있으면 맞는 학생은 원문 확인 그대로다."""
    converted = record(addAplyQlfcCndCn=EXTRA + ", 그 밖은 공고문 참조")
    found = check(
        {
            "conditions": [item("추가 자격", "job_status", "in", '["unemployed"]', "미취업 청년")],
            "covered": [],
        },
        {"추가 자격": EXTRA + ", 그 밖은 공고문 참조"},
    )
    merged = merge(converted, found, {"추가 자격": EXTRA + ", 그 밖은 공고문 참조"})
    requirements = [
        Requirement(
            id=str(index),
            clause_no=d.clause_no,
            field=d.field,
            operator=d.operator,
            value=d.value,
            basis=d.basis,
            is_ambiguous=d.is_ambiguous,
        )
        for index, d in enumerate(merged.requirements)
    ]
    employed = check_eligibility(requirements, Profile(job_status="employed"), basis_date=TODAY)
    unemployed = check_eligibility(requirements, Profile(job_status="unemployed"), basis_date=TODAY)
    assert employed.status == "ineligible"
    assert (unemployed.status, unemployed.display_status) == ("undetermined", "needs_review")


def _draft(field: str, operator: str, value: Any) -> RequirementDraft:
    return RequirementDraft(
        clause_no=1,
        field=field,
        operator=operator,
        value=value,
        basis=None,
        evidence_text="e",
        is_ambiguous=False,
    )


# ── 모델 부르기 ──────────────────────────────────────────────────────────────


async def test_the_model_is_called_once_with_the_tool_forced() -> None:
    llm = ScriptedLlm(
        call(
            SUBMIT,
            conditions=[item("참여 제한", "enrollment_status", "neq", '"enrolled"', "재학생 제외")],
            covered=["참여 제한"],
        )
    )
    found = await extract(llm, model="gemini-3.8-flash", texts={"참여 제한": "재학생 제외"})
    assert found.submitted and found.covered == ("참여 제한",) and found.reply is not None
    (request,) = llm.requests
    assert (request.model, request.force_tool, request.tools) == (
        "gemini-3.8-flash",
        SUBMIT,
        [SUBMIT],
    )
    assert "[참여 제한]\n재학생 제외" in request.turns[0].text


async def test_no_submission_moves_nothing() -> None:
    found = await extract(ScriptedLlm("글로만 답했다"), model="m", texts={"추가 자격": EXTRA})
    assert (found.submitted, found.conditions, found.covered) == (False, (), ())


def test_hashes_follow_the_engine_version_and_model() -> None:
    assert refined_hash("h", "a") != refined_hash("h", "b") != refined_hash("g", "b")
    assert refined_hash("h", "a") != "h"  # 켜면 서술형 글이 있는 정책을 한 번씩 다시 저장한다


def test_the_switch_is_off_by_default() -> None:
    llm = ScriptedLlm()
    assert youth_refiner(Settings(_env_file=None), llm) is None  # type: ignore[call-arg]
    on = Settings(_env_file=None, youth_text_enabled=True)  # type: ignore[call-arg]
    assert youth_refiner(on, None) is None  # 모델 클라이언트가 없으면 지금처럼
    refiner = youth_refiner(on, llm)
    assert refiner is not None and refiner.model == "gemini-3.8-flash"
