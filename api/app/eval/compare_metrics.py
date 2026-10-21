"""모델 비교 실험의 셈(docs/LLM_모델_선정.md "비교 실험"). DB·모델 없이 도는 순수 함수만 둔다.

- 요건 비교는 조건 하나를 (항목, 연산자, 값, 기준)으로 보고 조항 번호는 보지 않는다(모델마다 번호를 다르게 붙여도
  같은 조건이면 같다). 같은 조항 안의 OR 묶음까지 맞는지는 판정 혼동행렬이 본다.
- 판정은 앱과 같은 판정 엔진으로 가상 프로필마다 한다. 핵심 지표는 "실제 적격 → 부적격"(놓치면 학생이 지원을
  포기한다)이다.
"""

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.eligibility import Department, Profile, Requirement, check_eligibility

Condition = tuple[str, str, str, str]  # (field, operator, value JSON, basis)


def _normal(value: Any) -> Any:
    """같은 뜻의 값을 같게 쓴다: 3.0 → 3, [3, 2] → [2, 3](값 목록은 순서가 뜻이 없다)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        items = [_normal(one) for one in value]
        if all(not isinstance(one, (dict, list)) for one in items):
            return sorted(items, key=lambda one: json.dumps(one, ensure_ascii=False))
        return items
    if isinstance(value, dict):
        return {key: _normal(one) for key, one in value.items()}
    return value


def condition_key(requirement: Mapping[str, Any]) -> Condition:
    value = json.dumps(_normal(requirement.get("value")), ensure_ascii=False, sort_keys=True)
    return (
        str(requirement.get("field")),
        str(requirement.get("operator")),
        value,
        str(requirement.get("basis") or ""),
    )


def conditions(requirements: Iterable[Mapping[str, Any]]) -> set[Condition]:
    return {condition_key(one) for one in requirements}


@dataclass
class Match:
    """조건 일치 셈(여러 공고를 더한다). 정답이 있으면 정밀도·재현율, 없으면 두 모델의 일치율로 쓴다."""

    both: int = 0
    only_predicted: int = 0
    only_expected: int = 0

    def add(self, predicted: set[Condition], expected: set[Condition]) -> None:
        self.both += len(predicted & expected)
        self.only_predicted += len(predicted - expected)
        self.only_expected += len(expected - predicted)

    @property
    def precision(self) -> float | None:
        total = self.both + self.only_predicted
        return self.both / total if total else None

    @property
    def recall(self) -> float | None:
        total = self.both + self.only_expected
        return self.both / total if total else None

    @property
    def f1(self) -> float | None:
        """조건을 하나도 못 낸 모델은 0이다(셀 것이 아예 없을 때만 None)."""
        total = 2 * self.both + self.only_predicted + self.only_expected
        return 2 * self.both / total if total else None

    @property
    def jaccard(self) -> float | None:
        total = self.both + self.only_predicted + self.only_expected
        return self.both / total if total else None


def as_requirements(requirements: Sequence[Mapping[str, Any]]) -> list[Requirement]:
    return [
        Requirement(
            id=f"r{index}",
            clause_no=int(one.get("clause_no") or index + 1),
            field=str(one.get("field")),
            operator=str(one.get("operator")),
            value=one.get("value"),
            basis=one.get("basis"),
            is_ambiguous=bool(one.get("is_ambiguous")),
        )
        for index, one in enumerate(requirements)
    ]


def judge(
    requirements: Sequence[Mapping[str, Any]],
    profile: Profile,
    *,
    basis: date,
    departments: Sequence[Department],
    known: bool = True,
) -> str:
    """eligible·undetermined·ineligible. 요건을 못 읽은 결과(known=False)는 앱처럼 지원 가능으로 내보내지 않는다."""
    try:
        return check_eligibility(
            as_requirements(requirements),
            profile,
            basis_date=basis,
            departments=departments,
            requirements_known=known,
        ).status
    except Exception:  # 값 모양이 틀린 요건 — 앱은 "판정하지 못함"(원문 확인)으로 본다
        return "undetermined"


STATUSES = ("eligible", "undetermined", "ineligible")


@dataclass
class Confusion:
    """기준(정답 또는 앞 모델)의 판정 → 비교 모델의 판정. 칸은 (기준, 비교)다."""

    cells: dict[tuple[str, str], int] = field(default_factory=dict)

    def add(self, reference: str, compared: str) -> None:
        self.cells[(reference, compared)] = self.cells.get((reference, compared), 0) + 1

    @property
    def total(self) -> int:
        return sum(self.cells.values())

    @property
    def agree(self) -> int:
        return sum(count for (a, b), count in self.cells.items() if a == b)

    @property
    def eligible_to_ineligible(self) -> int:
        return self.cells.get(("eligible", "ineligible"), 0)

    @property
    def ineligible_to_eligible(self) -> int:
        return self.cells.get(("ineligible", "eligible"), 0)

    def table(self) -> list[list[int]]:
        return [[self.cells.get((a, b), 0) for b in STATUSES] for a in STATUSES]


def percentile(values: Sequence[float], q: float) -> float | None:
    """가장 가까운 순위(nearest rank) — 지표 집계(percentile_disc)와 같은 방식."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]
