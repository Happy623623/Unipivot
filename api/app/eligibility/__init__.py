"""자격 판정 엔진 (S1-3). 규칙은 docs/판정엔진_규칙.md에 있다.

judgment = check_eligibility(requirements, profile, basis_date=..., departments=...)
row = judgment.storage_row()  # eligibility_results에 저장
"""

from app.eligibility.catalog import ALLOWED_OPERATORS
from app.eligibility.dates import KST, age_on, resolve_basis_date, to_kst_date
from app.eligibility.describe import (
    clause_rows,
    condition_rows,
    condition_text,
    label,
    reason_text,
    user_value_text,
)
from app.eligibility.engine import (
    RequirementError,
    check_eligibility,
    evaluate_condition,
    requirement_problem,
)
from app.eligibility.models import (
    ClauseResult,
    ConditionResult,
    Department,
    Judgment,
    Profile,
    Requirement,
)

__all__ = [
    "ALLOWED_OPERATORS",
    "KST",
    "ClauseResult",
    "ConditionResult",
    "Department",
    "Judgment",
    "Profile",
    "Requirement",
    "RequirementError",
    "age_on",
    "check_eligibility",
    "clause_rows",
    "condition_rows",
    "condition_text",
    "evaluate_condition",
    "label",
    "reason_text",
    "requirement_problem",
    "resolve_basis_date",
    "to_kst_date",
    "user_value_text",
]
