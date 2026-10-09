"""판정 엔진 입출력. DB·LLM·시계와 무관한 순수 데이터다."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from typing import Any, Literal

Outcome = Literal["pass", "fail", "unknown"]
UnknownReason = Literal["missing_profile", "ambiguous", "unsupported_field", "basis_mismatch"]
Status = Literal["eligible", "ineligible", "undetermined"]
DisplayStatus = Literal["eligible", "missing_info", "needs_review", "ineligible"]


@dataclass(frozen=True)
class Requirement:
    """requirements 행 하나 = 조건 하나. 같은 clause_no끼리 OR, 서로 다른 clause_no끼리 AND."""

    id: str
    clause_no: int
    field: str
    operator: str
    value: Any
    basis: str | None = None
    is_ambiguous: bool = False
    evidence_text: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Requirement:
        """requirements 행(dict). DB의 uuid는 문자열로 바꿔 저장·JSON에 그대로 쓴다."""
        values = {f.name: row[f.name] for f in fields(cls) if f.name in row}
        values["id"] = str(values["id"])
        values["is_ambiguous"] = bool(values.get("is_ambiguous"))
        return cls(**values)


@dataclass(frozen=True)
class Profile:
    """판정에 쓰는 프로필 값. None은 미입력이다."""

    department: str | None = None
    grade: int | None = None
    enrollment_status: str | None = None
    semesters_completed: int | None = None
    credits_total: Decimal | int | None = None
    credits_last_semester: Decimal | int | None = None
    gpa_total: Decimal | float | None = None
    gpa_last_semester: Decimal | float | None = None
    gpa_scale: Decimal | float | None = None  # None이면 4.5
    birth_date: date | None = None
    military_service_months: int | None = None
    region_sido: str | None = None
    region_sigungu: str | None = None
    income_bracket: int | None = None
    median_income_pct: int | None = None
    welfare_status: str | None = None
    is_international: bool | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Profile:
        """profiles 행(dict)에서 판정에 쓰는 칸만 골라 만든다."""
        return cls(**{f.name: row[f.name] for f in fields(cls) if f.name in row})


@dataclass(frozen=True)
class Department:
    """departments 행: 학과 → 단과대학 → 계열."""

    name: str
    college: str
    field_group: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Department:
        """departments 행(dict). is_active·sort_order 같은 다른 칸은 무시한다."""
        return cls(name=row["name"], college=row["college"], field_group=row["field_group"])


def index_departments(
    departments: Iterable[Department] | Mapping[str, Department],
) -> dict[str, Department]:
    """학과 이름 → 학과 행."""
    if isinstance(departments, Mapping):
        return dict(departments)
    return {department.name: department for department in departments}


@dataclass(frozen=True)
class ConditionResult:
    """조건 하나의 결과. user_value는 비교에 쓴 내 값(나이는 기준일의 만 나이)."""

    requirement_id: str
    clause_no: int
    field: str
    outcome: Outcome
    unknown_reason: UnknownReason | None = None
    user_value: Any = None


@dataclass(frozen=True)
class ClauseResult:
    """묶음 하나의 결과."""

    clause_no: int
    outcome: Outcome
    condition_count: int


@dataclass(frozen=True)
class Judgment:
    """공고 하나 × 사용자 한 명의 판정."""

    status: Status
    display_status: DisplayStatus
    basis_date: date
    clauses: tuple[ClauseResult, ...]
    conditions: tuple[ConditionResult, ...]
    missing_fields: tuple[str, ...]
    reason_text: str

    def storage_row(self) -> dict[str, Any]:
        """eligibility_results에 저장할 값. requirements_version은 호출하는 쪽이 공고에서 넣는다."""
        return {
            "status": self.status,
            "condition_results": [
                {
                    "requirement_id": c.requirement_id,
                    "clause_no": c.clause_no,
                    "outcome": c.outcome,
                    "unknown_reason": c.unknown_reason,
                    "user_value": _jsonable(c.user_value),
                }
                for c in self.conditions
            ],
            "missing_fields": list(self.missing_fields),
            "reason_text": self.reason_text,
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
