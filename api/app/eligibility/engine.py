"""자격 판정 엔진 (docs/판정엔진_규칙.md).

요건(requirements 행) × 프로필 → 3상태(eligible / ineligible / undetermined).
LLM·DB·현재 시각을 쓰지 않는 순수 함수다. 날짜가 필요하면 호출하는 쪽이 기준일을 넘긴다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import groupby
from typing import Any

from app.eligibility.catalog import (
    ALLOWED_OPERATORS,
    COMPARABLE_REGION_BASES,
    DEFAULT_GPA_SCALE,
    DEPARTMENT_LEVELS,
    ENUM_LABELS,
    GPA_FIELDS,
    NUMBER_FIELDS,
    REGION_BASIS_LABELS,
)
from app.eligibility.dates import age_on, months_after
from app.eligibility.describe import reason_text
from app.eligibility.models import (
    ClauseResult,
    ConditionResult,
    Department,
    DisplayStatus,
    Judgment,
    Outcome,
    Profile,
    Requirement,
    Status,
    UnknownReason,
    index_departments,
)
from app.eligibility.regions import (
    normalize_sido,
    normalize_sigungu,
    parse_region,
    region_verdict,
)


class RequirementError(ValueError):
    """요건 값의 모양이 규칙과 다르다. 판정에서는 모호한 조건(원문 확인 필요)으로 처리한다."""


@dataclass(frozen=True)
class _Eval:
    outcome: Outcome
    reason: UnknownReason | None = None
    user_value: Any = None


Evaluator = Callable[[Profile, date, Mapping[str, Department]], _Eval]


def check_eligibility(
    requirements: Iterable[Requirement],
    profile: Profile,
    *,
    basis_date: date,
    departments: Iterable[Department] | Mapping[str, Department] = (),
) -> Judgment:
    """한 사용자를 공고 요건 전체로 판정한다. 요건이 하나도 없으면 지원 가능이다."""
    index = index_departments(departments)
    ordered = sorted(requirements, key=lambda r: r.clause_no)
    conditions = tuple(evaluate_condition(r, profile, basis_date, index) for r in ordered)
    clauses = tuple(
        _clause(clause_no, list(members))
        for clause_no, members in groupby(conditions, key=lambda c: c.clause_no)
    )

    outcomes = [clause.outcome for clause in clauses]
    status: Status
    if "fail" in outcomes:
        status = "ineligible"  # 불충족 묶음이 하나라도 확실하면
    elif all(outcome == "pass" for outcome in outcomes):
        status = "eligible"
    else:
        status = "undetermined"

    missing: tuple[str, ...] = ()
    if status == "undetermined":
        # 결과가 모름인 묶음에서, 프로필이 비어 모름이 된 조건의 항목만 묻는다
        unknown = {clause.clause_no for clause in clauses if clause.outcome == "unknown"}
        missing = tuple(
            dict.fromkeys(
                c.field
                for c in conditions
                if c.clause_no in unknown and c.unknown_reason == "missing_profile"
            )
        )

    display: DisplayStatus
    if status == "undetermined":
        display = "missing_info" if missing else "needs_review"
    else:
        display = status

    judgment = Judgment(
        status=status,
        display_status=display,
        basis_date=basis_date,
        clauses=clauses,
        conditions=conditions,
        missing_fields=missing,
        reason_text="",
    )
    return replace(judgment, reason_text=reason_text(judgment, ordered, profile, index))


def evaluate_condition(
    req: Requirement,
    profile: Profile,
    basis_date: date,
    departments: Mapping[str, Department],
) -> ConditionResult:
    """조건 하나. 우선순위: other → 모호 표시 → 값 모양 → 기준 다름 → 프로필 없음 → 비교."""
    if req.field == "other":
        result = _Eval("unknown", "unsupported_field")
    else:
        try:
            result = _compile(req)(profile, basis_date, departments)
        except RequirementError:
            result = _Eval("unknown", "ambiguous")
        if req.is_ambiguous:
            result = _Eval("unknown", "ambiguous", result.user_value)
    return ConditionResult(
        requirement_id=req.id,
        clause_no=req.clause_no,
        field=req.field,
        outcome=result.outcome,
        unknown_reason=result.reason,
        user_value=result.user_value,
    )


def requirement_problem(req: Requirement) -> str | None:
    """요건 추출 결과 검증용(S1-4). 판정할 수 있는 모양이면 None, 아니면 고칠 점을 돌려준다."""
    if req.clause_no < 1:
        return "clause_no는 1 이상이어야 한다"
    if req.field in ("region", "department") and req.basis is None:
        return f"{req.field} 조건에는 basis가 있어야 한다"
    try:
        _compile(req)
    except RequirementError as exc:
        return str(exc)
    if req.field == "region":
        bad = [text for text in _string_list(req, "거주지역") if parse_region(text) is None]
        if bad:
            return f'거주지역 값은 시도로 시작해야 한다(예: "경기도 안산시"): {bad}'
    return None


def _clause(clause_no: int, members: list[ConditionResult]) -> ClauseResult:
    outcomes = [member.outcome for member in members]
    outcome: Outcome
    if "pass" in outcomes:
        outcome = "pass"
    elif all(item == "fail" for item in outcomes):
        outcome = "fail"
    else:
        outcome = "unknown"
    return ClauseResult(clause_no=clause_no, outcome=outcome, condition_count=len(members))


def _compile(req: Requirement) -> Evaluator:
    """요건 하나를 검사 함수로 만든다. 값 모양이 틀리면 RequirementError."""
    allowed = ALLOWED_OPERATORS.get(req.field)
    if allowed is None:
        raise RequirementError(f"알 수 없는 요건 항목: {req.field}")
    if req.operator not in allowed:
        raise RequirementError(f"{req.field}에는 {req.operator} 연산자를 쓸 수 없다")
    if req.field not in ("region", "department") and req.basis is not None:
        raise RequirementError(f"{req.field}에는 basis를 쓰지 않는다")
    if req.field == "other":
        return lambda *_: _Eval("unknown", "unsupported_field")
    if req.field in NUMBER_FIELDS:
        return _number(req)
    if req.field in GPA_FIELDS:
        return _gpa(req)
    if req.field in ENUM_LABELS:
        return _enum(req)
    if req.field == "age":
        return _age(req)
    if req.field == "region":
        return _region(req)
    if req.field == "department":
        return _department(req)
    return _boolean(req)


def _outcome(ok: bool) -> Outcome:
    return "pass" if ok else "fail"


def _decimal(value: Any, what: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        raise RequirementError(f"{what} 값은 숫자여야 한다: {value!r}")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise RequirementError(f"{what} 값은 숫자여야 한다: {value!r}") from exc
    if not number.is_finite():
        raise RequirementError(f"{what} 값은 유한한 숫자여야 한다: {value!r}")
    return number


def _whole(value: Any, what: str) -> int:
    number = _decimal(value, what)
    if number != number.to_integral_value():
        raise RequirementError(f"{what} 값은 정수여야 한다: {value!r}")
    return int(number)


def _bounds(value: Any, convert: Callable[[Any], Any]) -> tuple[Any, Any]:
    if not isinstance(value, Mapping):
        raise RequirementError('between 값은 {"min": …, "max": …} 모양이어야 한다')
    low = None if value.get("min") is None else convert(value["min"])
    high = None if value.get("max") is None else convert(value["max"])
    if low is None and high is None:
        raise RequirementError("between에는 min이나 max가 있어야 한다")
    if low is not None and high is not None and low > high:
        raise RequirementError("between의 min이 max보다 크다")
    return low, high


def _predicate(operator: str, value: Any, convert: Callable[[Any], Any]) -> Callable[[Any], bool]:
    """연산자와 값으로 비교 함수를 만든다. 이상·이하·between은 경계를 포함한다."""
    if operator in ("eq", "neq"):
        target = convert(value)
        if operator == "eq":
            return lambda actual: actual == target
        return lambda actual: actual != target
    if operator in ("in", "not_in"):
        if not isinstance(value, list) or not value:
            raise RequirementError("in·not_in 값은 비어 있지 않은 목록이어야 한다")
        targets = [convert(item) for item in value]
        if operator == "in":
            return lambda actual: actual in targets
        return lambda actual: actual not in targets
    if operator == "gte":
        target = convert(value)
        return lambda actual: actual >= target
    if operator == "lte":
        target = convert(value)
        return lambda actual: actual <= target
    if operator == "between":
        low, high = _bounds(value, convert)
        return lambda actual: (low is None or actual >= low) and (high is None or actual <= high)
    raise RequirementError(f"알 수 없는 연산자: {operator}")


def _string_list(req: Requirement, what: str) -> list[str]:
    values = [req.value] if req.operator in ("eq", "neq") else req.value
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(item, str) and item.strip() for item in values)
    ):
        raise RequirementError(f"{what} 값은 문자열이어야 한다 (in·not_in이면 비어 있지 않은 목록)")
    return values


def _set_result(verdicts: list[str], positive: bool, shown: Any) -> _Eval:
    """in·eq(positive)와 not_in·neq. 하나라도 일치하면 확정하고, 아니면 모를 이유가 있는지 본다."""
    if "match" in verdicts:
        return _Eval("pass" if positive else "fail", user_value=shown)
    if "unparseable" in verdicts:
        return _Eval("unknown", "ambiguous", shown)
    if "less_specific" in verdicts:
        return _Eval("unknown", "missing_profile", shown)
    return _Eval("fail" if positive else "pass", user_value=shown)


def _number(req: Requirement) -> Evaluator:
    field = req.field

    def convert(value: Any) -> Decimal:
        return _decimal(value, field)

    predicate = _predicate(req.operator, req.value, convert)

    def evaluate(
        profile: Profile, basis_date: date, departments: Mapping[str, Department]
    ) -> _Eval:
        actual = getattr(profile, field)
        if actual is None:
            return _Eval("unknown", "missing_profile")
        return _Eval(_outcome(predicate(convert(actual))), user_value=actual)

    return evaluate


def _gpa(req: Requirement) -> Evaluator:
    field, value, scale = req.field, req.value, DEFAULT_GPA_SCALE
    if isinstance(value, Mapping) and "scale" in value:
        scale = _decimal(value["scale"], "만점")
        if req.operator == "between":
            value = {"min": value.get("min"), "max": value.get("max")}
        elif "value" in value:
            value = value["value"]
        else:
            raise RequirementError('만점을 적을 때는 {"value": 80, "scale": 100} 모양이어야 한다')

    def convert(item: Any) -> Decimal:
        return _decimal(item, field)

    predicate = _predicate(req.operator, value, convert)

    def evaluate(
        profile: Profile, basis_date: date, departments: Mapping[str, Department]
    ) -> _Eval:
        actual = getattr(profile, field)
        mine = (
            DEFAULT_GPA_SCALE if profile.gpa_scale is None else _decimal(profile.gpa_scale, "만점")
        )
        if mine != scale:
            return _Eval("unknown", "basis_mismatch", actual)  # 만점이 다르면 환산하지 않는다
        if actual is None:
            return _Eval("unknown", "missing_profile")
        return _Eval(_outcome(predicate(convert(actual))), user_value=actual)

    return evaluate


def _enum(req: Requirement) -> Evaluator:
    field, allowed = req.field, ENUM_LABELS[req.field]

    def convert(value: Any) -> str:
        if not isinstance(value, str) or value not in allowed:
            raise RequirementError(f"{field} 값은 {', '.join(allowed)} 중 하나여야 한다: {value!r}")
        return value

    predicate = _predicate(req.operator, req.value, convert)

    def evaluate(
        profile: Profile, basis_date: date, departments: Mapping[str, Department]
    ) -> _Eval:
        actual = getattr(profile, field)
        if actual is None:
            return _Eval("unknown", "missing_profile")
        return _Eval(_outcome(predicate(actual)), user_value=actual)

    return evaluate


def _boolean(req: Requirement) -> Evaluator:
    field = req.field

    def convert(value: Any) -> bool:
        if not isinstance(value, bool):
            raise RequirementError(f"{field} 값은 true나 false여야 한다: {value!r}")
        return value

    predicate = _predicate(req.operator, req.value, convert)

    def evaluate(
        profile: Profile, basis_date: date, departments: Mapping[str, Department]
    ) -> _Eval:
        actual = getattr(profile, field)
        if actual is None:
            return _Eval("unknown", "missing_profile")
        return _Eval(_outcome(predicate(actual)), user_value=actual)

    return evaluate


def _age(req: Requirement) -> Evaluator:
    """만 나이. 상한은 병역 복무 개월만큼 늘릴 수 있다 (military_extension)."""
    extension: Any = None
    if req.operator == "gte":
        low, high = _whole(req.value, "나이"), None
    elif req.operator == "lte":
        low, high = None, _whole(req.value, "나이")
    else:
        low, high = _bounds(req.value, lambda item: _whole(item, "나이"))
        extension = req.value.get("military_extension")
    enabled, cap = _military_extension(extension, has_upper=high is not None)

    def evaluate(
        profile: Profile, basis_date: date, departments: Mapping[str, Department]
    ) -> _Eval:
        birth = profile.birth_date
        if birth is None:
            return _Eval("unknown", "missing_profile")
        age = age_on(birth, basis_date)
        if low is not None and basis_date < months_after(birth, 12 * low):
            return _Eval("fail", user_value=age)
        if high is None or basis_date < months_after(birth, 12 * (high + 1)):
            return _Eval("pass", user_value=age)
        if not enabled:
            return _Eval("fail", user_value=age)
        months = profile.military_service_months
        if months is None:
            if cap is not None and basis_date >= months_after(birth, 12 * (high + 1) + cap):
                return _Eval("fail", user_value=age)  # 최대로 늘려도 넘는다
            return _Eval("unknown", "missing_profile", age)
        extra = months if cap is None else min(months, cap)
        return _Eval(
            _outcome(basis_date < months_after(birth, 12 * (high + 1) + extra)), user_value=age
        )

    return evaluate


def _military_extension(raw: Any, *, has_upper: bool) -> tuple[bool, int | None]:
    """(연장 여부, 최대 개월). 공고에 상한이 없으면 복무 개월 전부를 더한다."""
    if raw is None or raw is False:
        return False, None
    if not has_upper:
        raise RequirementError("병역 연장은 나이 상한(max)이 있을 때만 쓴다")
    if raw is True:
        return True, None
    if isinstance(raw, Mapping) and set(raw) == {"max_months"}:
        cap = _whole(raw["max_months"], "병역 연장 상한")
        if cap < 0:
            raise RequirementError("병역 연장 상한은 0 이상이어야 한다")
        return True, cap
    raise RequirementError('military_extension은 true, false, {"max_months": 36} 중 하나여야 한다')


def _region(req: Requirement) -> Evaluator:
    basis = req.basis or "unspecified"
    if basis not in REGION_BASIS_LABELS:
        raise RequirementError(
            f"거주지역 basis는 {', '.join(REGION_BASIS_LABELS)} 중 하나여야 한다"
        )
    entries = [parse_region(text) for text in _string_list(req, "거주지역")]
    positive = req.operator in ("eq", "in")

    def evaluate(
        profile: Profile, basis_date: date, departments: Mapping[str, Department]
    ) -> _Eval:
        sido = normalize_sido(profile.region_sido)
        sigungu = normalize_sigungu(profile.region_sigungu)
        shown = " ".join(part for part in (sido or profile.region_sido, sigungu) if part) or None
        if basis not in COMPARABLE_REGION_BASES:
            return _Eval("unknown", "basis_mismatch", shown)  # 실거주·출신 고교·보호자 주소
        if sido is None:
            return _Eval("unknown", "missing_profile", shown)
        return _set_result([region_verdict(e, sido, sigungu) for e in entries], positive, shown)

    return evaluate


_LEVEL_ATTRIBUTE = {"department": "name", "college": "college", "field_group": "field_group"}


def _department(req: Requirement) -> Evaluator:
    level = req.basis or "department"
    if level not in DEPARTMENT_LEVELS:
        raise RequirementError(f"학과 basis는 {', '.join(DEPARTMENT_LEVELS)} 중 하나여야 한다")
    names = _string_list(req, "학과")
    attribute = _LEVEL_ATTRIBUTE[level]
    positive = req.operator in ("eq", "in")

    def evaluate(
        profile: Profile, basis_date: date, departments: Mapping[str, Department]
    ) -> _Eval:
        if profile.department is None:
            return _Eval("unknown", "missing_profile")
        mine = departments.get(profile.department)
        if mine is None:
            return _Eval("unknown", "missing_profile", profile.department)
        known = {getattr(item, attribute) for item in departments.values()}
        actual = getattr(mine, attribute)
        # 학과 목록에 없는 이름은 이름이 달라서일 수 있으니 불충족으로 보지 않는다
        verdicts = [
            "match" if name == actual else ("no" if name in known else "unparseable")
            for name in names
        ]
        return _set_result(verdicts, positive, profile.department)

    return evaluate
