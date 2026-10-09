"""판정 결과를 화면 문구로 바꾼다: 공고 상세 판정표의 조건·내 값, 카드의 사유 한 줄."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Any

from app.eligibility.catalog import (
    COMPARABLE_REGION_BASES,
    DEFAULT_GPA_SCALE,
    DEPARTMENT_LEVELS,
    ENUM_LABELS,
    FIELD_LABELS,
    GPA_FIELDS,
    INPUT_LABELS,
    REGION_BASIS_LABELS,
    UNITS,
)
from app.eligibility.models import (
    ConditionResult,
    Department,
    Judgment,
    Profile,
    Requirement,
    index_departments,
)
from app.eligibility.regions import normalize_sido, normalize_sigungu


def label(req: Requirement) -> str:
    """판정표 항목 이름. 학과 조건은 비교 단위(학과·단과대학·계열)를 쓴다."""
    if req.field == "department":
        return DEPARTMENT_LEVELS.get(req.basis or "department", "학과")
    return FIELD_LABELS.get(req.field, req.field)


def condition_text(req: Requirement) -> str:
    """판정표 '조건' 칸. 값 모양이 틀린 요건은 근거 문장을 보여준다."""
    try:
        return _condition_text(req)
    except (AttributeError, KeyError, TypeError, ValueError, ArithmeticError):
        return req.evidence_text or "원문 조건"


def user_value_text(
    req: Requirement,
    result: ConditionResult,
    profile: Profile,
    departments: Iterable[Department] | Mapping[str, Department] = (),
) -> str | None:
    """판정표 '내 값' 칸. 프로필이 비어 있으면 None."""
    field = req.field
    if field == "other":
        return None
    if field == "age":
        if profile.birth_date is None or result.user_value is None:
            return None
        text = f"만 {result.user_value}세"
        if _has_military_extension(req) and profile.military_service_months is not None:
            text += f" · 병역 {profile.military_service_months}개월"
        return text
    if field == "region":
        sido = normalize_sido(profile.region_sido) or profile.region_sido
        parts = [part for part in (sido, normalize_sigungu(profile.region_sigungu)) if part]
        return " ".join(parts) or None
    if field == "department":
        if profile.department is None:
            return None
        mine = index_departments(departments).get(profile.department)
        level = req.basis or "department"
        if mine is None or level == "department":
            return profile.department
        unit = mine.college if level == "college" else mine.field_group
        return f"{profile.department} ({unit})"
    value = getattr(profile, field, None)
    if value is None:
        return None
    if field in GPA_FIELDS:
        text = format(Decimal(str(value)), ".2f")
        scale = DEFAULT_GPA_SCALE if profile.gpa_scale is None else Decimal(str(profile.gpa_scale))
        return text if scale == DEFAULT_GPA_SCALE else f"{text} ({_num(scale)} 만점)"
    if field in UNITS:
        return f"{_num(value)}{UNITS[field]}"
    if field in ENUM_LABELS:
        return ENUM_LABELS[field].get(value, str(value))
    if field == "is_international":
        return "유학생" if value else "유학생 아님"
    return str(value)


def reason_text(
    judgment: Judgment,
    requirements: Iterable[Requirement],
    profile: Profile,
    departments: Iterable[Department] | Mapping[str, Department] = (),
) -> str:
    """카드·상세 상단의 사유 한 줄 (eligibility_results.reason_text)."""
    by_id = {req.id: req for req in requirements}
    if judgment.status == "eligible":
        return "모든 조건 충족"
    if judgment.status == "ineligible":
        failed = [clause.clause_no for clause in judgment.clauses if clause.outcome == "fail"]
        members = [c for c in judgment.conditions if c.clause_no == failed[0]]
        if len(members) == 1:
            req = by_id[members[0].requirement_id]
            text = f"{label(req)}: {condition_text(req)}"
            current = user_value_text(req, members[0], profile, departments)
            if current:
                text += f" (현재 {current})"
        else:
            options = ", ".join(_label_and_condition(by_id[c.requirement_id]) for c in members)
            text = f"다음 중 하나: {options}"
        if len(failed) > 1:
            text += f" 외 {len(failed) - 1}개"
        return text
    if judgment.missing_fields:
        names = "·".join(_input_label(field, profile) for field in judgment.missing_fields)
        return f"{names} 입력 필요"
    unknown = {clause.clause_no for clause in judgment.clauses if clause.outcome == "unknown"}
    first = next(
        c for c in judgment.conditions if c.clause_no in unknown and c.outcome == "unknown"
    )
    req = by_id[first.requirement_id]
    if req.field == "other":
        return f"원문 확인 필요: {condition_text(req)}"
    return f"원문 확인 필요: {_label_and_condition(req)}"


def condition_rows(
    judgment: Judgment,
    requirements: Iterable[Requirement],
    profile: Profile,
    departments: Iterable[Department] | Mapping[str, Department] = (),
) -> list[dict[str, Any]]:
    """공고 상세 API의 eligibility.conditions (API 명세 v0.4 5장)."""
    by_id = {req.id: req for req in requirements}
    index = index_departments(departments)
    rows = []
    for result in judgment.conditions:
        req = by_id[result.requirement_id]
        rows.append(
            {
                "requirement_id": req.id,
                "clause_no": req.clause_no,
                "field": req.field,
                "label": label(req),
                "condition_text": condition_text(req),
                "user_value_text": user_value_text(req, result, profile, index),
                "outcome": result.outcome,
                "unknown_reason": result.unknown_reason,
                "evidence_text": req.evidence_text,
                "is_ambiguous": req.is_ambiguous,
            }
        )
    return rows


def clause_rows(judgment: Judgment) -> list[dict[str, Any]]:
    """공고 상세 API의 eligibility.clauses."""
    return [
        {"clause_no": c.clause_no, "outcome": c.outcome, "condition_count": c.condition_count}
        for c in judgment.clauses
    ]


def _input_label(field: str, profile: Profile) -> str:
    if field == "age":
        return "생년월일" if profile.birth_date is None else "병역 복무 개월"
    return INPUT_LABELS.get(field, field)


def _label_and_condition(req: Requirement) -> str:
    return f"{label(req)} {condition_text(req)}"


def _has_military_extension(req: Requirement) -> bool:
    if req.operator != "between" or not isinstance(req.value, Mapping):
        return False
    return req.value.get("military_extension") not in (None, False)


def _condition_text(req: Requirement) -> str:
    field, op, value = req.field, req.operator, req.value
    if field == "other":
        if isinstance(value, Mapping) and value.get("text"):
            return str(value["text"])
        return req.evidence_text or "원문 조건"
    if field == "age":
        return _age_text(op, value)
    if field in GPA_FIELDS:
        return _gpa_text(op, value)
    if field in UNITS:
        unit = UNITS[field]
        return _phrase(op, value, lambda item: f"{_num(item)}{unit}")
    if field in ENUM_LABELS:
        names = ENUM_LABELS[field]
        return _phrase(op, value, lambda item: names[item])
    if field == "is_international":
        if not isinstance(value, bool):
            raise ValueError(value)
        wanted = value if op == "eq" else not value
        return "유학생" if wanted else "유학생 아님"
    if field == "region":
        text = _phrase(op, value, str, join=", ")
        if req.basis and req.basis not in COMPARABLE_REGION_BASES:
            text += f" ({REGION_BASIS_LABELS[req.basis]} 기준)"
        return text
    if field == "department":
        return _phrase(op, value, str)
    raise ValueError(field)


def _phrase(op: str, value: Any, fmt: Callable[[Any], str], *, join: str = "·") -> str:
    if op == "eq":
        return fmt(value)
    if op == "neq":
        return f"{fmt(value)} 제외"
    if op in ("in", "not_in"):
        if not isinstance(value, list) or not value:
            raise ValueError(value)
        text = join.join(fmt(item) for item in value)
        return text if op == "in" else f"{text} 제외"
    if op == "gte":
        return f"{fmt(value)} 이상"
    if op == "lte":
        return f"{fmt(value)} 이하"
    if op == "between":
        low, high = value.get("min"), value.get("max")
        if low is None:
            return f"{fmt(high)} 이하"
        if high is None:
            return f"{fmt(low)} 이상"
        return f"{fmt(low)}–{fmt(high)}"
    raise ValueError(op)


def _age_text(op: str, value: Any) -> str:
    if op == "gte":
        return f"만 {_num(value)}세 이상"
    if op == "lte":
        return f"만 {_num(value)}세 이하"
    low, high = value.get("min"), value.get("max")
    if low is None:
        text = f"만 {_num(high)}세 이하"
    elif high is None:
        text = f"만 {_num(low)}세 이상"
    else:
        text = f"만 {_num(low)}–{_num(high)}세"
    extension = value.get("military_extension")
    if isinstance(extension, Mapping):
        text += f" (병역 기간만큼 상한 연장, 최대 {_num(extension['max_months'])}개월)"
    elif extension is True:
        text += " (병역 기간만큼 상한 연장)"
    return text


def _gpa_text(op: str, value: Any) -> str:
    scale = DEFAULT_GPA_SCALE
    if isinstance(value, Mapping) and "scale" in value:
        scale = Decimal(str(value["scale"]))
        if op == "between":
            value = {"min": value.get("min"), "max": value.get("max")}
        else:
            value = value["value"]
    text = _phrase(op, value, _gpa_num if scale <= 5 else _num)
    if scale != DEFAULT_GPA_SCALE:
        text += f" ({_num(scale)}점 만점)"
    return text


def _num(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError(value)
    number = Decimal(str(value))
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.normalize(), "f")


def _gpa_num(value: Any) -> str:
    text = _num(value)
    return text if "." in text else f"{text}.0"
