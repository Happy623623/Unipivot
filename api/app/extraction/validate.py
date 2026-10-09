"""submit_requirements 검증: 스키마 → 판정 엔진 모양 검사 → 근거 대조 (PRD 6장).

첫 제출에 문제가 있으면 문제 목록을 모델에 돌려주고 한 번 더 받는다. 마지막 제출은 고쳐서 받고,
고친 내용(fixes)은 원문 확인 필요 사유가 된다.
- 모양이 틀린 조건은 other + 모호, 근거가 읽은 원문에 없는 조건은 모호로 저장한다
- 묶음 번호가 틀린 조건은 1번 묶음에 모호 조건으로 넣는다. 따로 묶음을 만들면 "또는"이었던 조건이
  "그리고"가 되어 지원 가능한 학생이 지원 어려움이 될 수 있어서다(모호 조건은 묶음을 불충족으로 만들지 않는다)
- 판정 기준일에 쓰이는 날짜(마감·기준일)가 게시일과 맞지 않으면 버린다. 틀린 연도는 나이 판정을 바꾼다
- requirements가 목록이 아니면 고칠 수 없으니 마지막 제출이어도 받지 않는다(추출 실패)
"""

import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.eligibility import ALLOWED_OPERATORS, KST, Department, Requirement, requirement_problem
from app.eligibility.catalog import DEPARTMENT_LEVELS, FIELD_LABELS
from app.extraction.models import AttachmentInput, DocumentDraft, RequirementDraft

_ELLIPSIS = re.compile(r"\.{3,}|…|⋯")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_DROP = str.maketrans({"|": None, '"': None, "'": None, "“": None, "”": None, "‘": None, "’": None})
_LEVEL_ATTRIBUTE = {"department": "name", "college": "college", "field_group": "field_group"}
_MAX_SUMMARY_CHARS = 400
_MAX_CLAUSE_NO = 999  # requirements.clause_no는 smallint다
_DEADLINE_TIME = time(23, 59)  # 날짜만 적힌 마감은 그날 23:59 KST
_DEADLINE_AFTER_POSTED = timedelta(
    days=400
)  # 게시일보다 이만큼 뒤의 마감은 연도를 잘못 읽은 것으로 본다
_BASIS_BEFORE_POSTED = timedelta(days=3 * 366)
_BASIS_AFTER_POSTED = timedelta(days=400)


class Evidence:
    """모델이 읽은 원문(제목·본문·읽은 첨부·원문 페이지). 근거 문장이 여기 있는지 본다.

    PDF·HWP 추출은 띄어쓰기와 줄 바꿈이 원문과 다를 수 있어서 공백·표 구분선·따옴표를 빼고 비교한다.
    근거를 "…"로 줄였으면 나뉜 조각이 같은 자료 안에 순서대로 있어야 한다.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []

    def add(self, text: str) -> None:
        if text.strip():
            self._parts.append(normalize(text))

    def contains(self, quote: str) -> bool:
        pieces = [normalize(piece) for piece in _ELLIPSIS.split(quote)]
        pieces = [piece for piece in pieces if piece]
        return bool(pieces) and any(_in_order(pieces, part) for part in self._parts)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_DROP)
    return "".join(text.split()).lower()


def _in_order(pieces: list[str], text: str) -> bool:
    position = 0
    for piece in pieces:
        found = text.find(piece, position)
        if found < 0:
            return False
        position = found + len(piece)
    return True


@dataclass(frozen=True)
class Submission:
    requirements: tuple[RequirementDraft, ...]
    documents: tuple[DocumentDraft, ...]
    apply_start_at: datetime | None
    deadline_at: datetime | None
    eligibility_basis_date: date | None
    easy_summary: str | None
    confidence: Decimal
    needs_review: bool
    review_note: str | None
    fixes: tuple[str, ...] = ()  # 마지막 제출에서 고쳐 넣은 것. 원문 확인 필요 사유가 된다


@dataclass(frozen=True)
class Context:
    evidence: Evidence
    attachments: Mapping[int, AttachmentInput]
    departments: Sequence[Department] = ()
    posted_on: date | None = None


class _Notes:
    """문제(모델에 돌려줄 것)와 고친 것(마지막 제출에서 저장 전에 바꾼 것)."""

    def __init__(self) -> None:
        self.problems: list[str] = []
        self.fixes: list[str] = []

    def add(self, problem: str, fix: str | None = None) -> None:
        self.problems.append(problem)
        if fix:
            self.fixes.append(fix)


def check_submission(
    args: Mapping[str, Any], context: Context, *, final: bool
) -> tuple[Submission | None, list[str]]:
    """(제출, 문제 목록). 문제가 없으면 그대로 받는다. 문제가 있으면 final일 때만 고쳐서 받는다."""
    notes = _Notes()
    raw_requirements = _listish(args.get("requirements"))
    if raw_requirements is None:
        notes.add("requirements는 목록이어야 한다(자격 제한이 없으면 빈 목록)")
        return None, notes.problems  # 요건을 알 수 없다. 빈 목록으로 저장하면 모두 지원 가능이 된다
    shift = _zero_based(raw_requirements)
    if shift:
        notes.add("clause_no는 1부터 쓴다", "0부터 센 묶음 번호를 1부터로 고침")
    requirements = [
        _requirement(no, item, shift, context, notes) for no, item in enumerate(raw_requirements, 1)
    ]

    raw_documents = _listish(args.get("documents", []))
    if raw_documents is None:
        notes.add("documents는 목록이어야 한다", "읽을 수 없는 서류 목록을 버림")
        raw_documents = []
    documents = [
        document
        for no, item in enumerate(raw_documents, 1)
        if (document := _document(no, item, context, notes)) is not None
    ]

    apply_start = _moment(args, "apply_start", time(0, 0), notes)
    deadline = _moment(args, "deadline", _DEADLINE_TIME, notes)
    deadline = _check_deadline(deadline, context.posted_on, notes)
    if apply_start and deadline and apply_start > deadline:
        notes.add(
            "apply_start가 deadline보다 늦다. 두 날짜를 확인해라",
            "마감보다 늦은 신청 시작일을 버림",
        )
        apply_start = None
    basis_date = _basis_date(args, context.posted_on, notes)

    confidence = _confidence(args.get("confidence"), notes)
    needs_review = args.get("needs_review", False)
    if not isinstance(needs_review, bool):
        notes.add("needs_review는 true나 false여야 한다")
        needs_review = True
    # 쉬운 설명은 학생에게 그대로 보인다. 공고 속 지시문이 링크를 끼워 넣지 못하게 주소를 지운다
    raw_summary = args.get("easy_summary")
    summary = (
        _text(" ".join(_URL.sub("", raw_summary).split())) if isinstance(raw_summary, str) else None
    )
    submission = Submission(
        requirements=tuple(requirements),
        documents=tuple(documents),
        apply_start_at=apply_start,
        deadline_at=deadline,
        eligibility_basis_date=basis_date,
        easy_summary=summary[:_MAX_SUMMARY_CHARS] if summary else None,
        confidence=confidence,
        needs_review=needs_review,
        review_note=_text(args.get("review_note")),
        fixes=tuple(dict.fromkeys(notes.fixes)),
    )
    if notes.problems and not final:
        return None, notes.problems
    return submission, notes.problems


def _listish(value: Any) -> list[Any] | None:
    """목록. 모델이 목록을 JSON 문자열로 보낸 경우도 받는다."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, list) else None


def _zero_based(items: list[Any]) -> bool:
    """묶음 번호를 0부터 셌는지. 그러면 모두 1씩 올려 묶음 구성을 그대로 살린다."""
    numbers = [_whole(item.get("clause_no")) for item in items if isinstance(item, Mapping)]
    valid = [number for number in numbers if number is not None]
    return bool(valid) and len(valid) == len(numbers) and min(valid) == 0


def _requirement(
    no: int, item: Any, shift: bool, context: Context, notes: _Notes
) -> RequirementDraft:
    where = f"requirements[{no}]"
    if not isinstance(item, Mapping):
        notes.add(f"{where}: 객체여야 한다", "읽을 수 없는 조건을 모호한 기타 조건으로 저장")
        return _as_other(1, None, "")
    evidence = _text(item.get("evidence_text"))
    clause_no = _whole(item.get("clause_no"))
    if clause_no is not None and shift:
        clause_no += 1
    clause_ok = clause_no is not None and 1 <= clause_no <= _MAX_CLAUSE_NO
    if not clause_ok:
        notes.add(
            f"{where}: clause_no는 1–{_MAX_CLAUSE_NO} 정수여야 한다",
            "묶음 번호가 틀린 조건을 1번 묶음의 모호한 조건으로 저장",
        )
        clause_no = 1

    field, operator = item.get("field"), item.get("operator")
    basis = _text(item.get("basis"))
    ambiguous = item.get("is_ambiguous", False)
    if not isinstance(ambiguous, bool):
        notes.add(f"{where}: is_ambiguous는 true나 false여야 한다")
        ambiguous = True
    problem: str | None = None
    value: Any = None
    if not isinstance(field, str) or field not in ALLOWED_OPERATORS:
        problem = f"field는 {', '.join(ALLOWED_OPERATORS)} 중 하나여야 한다: {field!r}"
    else:
        raw_value = item.get("value_json")
        try:
            # 문자열이 아닌 값을 그대로 넣었으면 그 값을 쓴다. NaN·Infinity는 DB(jsonb)가 받지 않는다
            value = (
                json.loads(raw_value, parse_constant=_reject_constant)
                if isinstance(raw_value, str)
                else raw_value
            )
            if value is None or not _finite(value):
                raise ValueError
        except (TypeError, ValueError):
            problem = f"value_json이 JSON 값이 아니다: {raw_value!r}"
        else:
            problem = requirement_problem(
                Requirement(
                    id=str(no),
                    clause_no=clause_no,
                    field=field,
                    operator=str(operator),
                    value=value,
                    basis=basis,
                    is_ambiguous=ambiguous,
                    evidence_text=evidence,
                )
            ) or _other_problem(field, value)
    if problem:
        label = FIELD_LABELS.get(field, str(field)) if isinstance(field, str) else str(field)
        notes.add(f"{where}({label}): {problem}", f"모양이 틀린 {label} 조건을 기타 조건으로 저장")
        return _as_other(clause_no, evidence, str(item.get("value_json", "")))

    if not evidence:
        notes.add(
            f"{where}: evidence_text가 비었다. 근거 문장을 원문에서 그대로 복사해라",
            "근거 문장이 없는 조건을 모호한 조건으로 저장",
        )
        ambiguous = True
    elif not context.evidence.contains(evidence):
        notes.add(
            f"{where}: 근거 문장이 읽은 원문에 없다. 고치거나 요약하지 말고 원문 그대로 복사해라:"
            f" {evidence!r}",
            "근거 문장을 원문에서 찾지 못한 조건을 모호한 조건으로 저장",
        )
        ambiguous = True
    if field == "department" and not _known_departments(value, basis, context.departments):
        ambiguous = True  # 규칙 4: 학과 목록에 없는 이름은 원문 그대로 두고 모호 조건
    return RequirementDraft(
        clause_no=clause_no,
        field=field,
        operator=str(operator),
        value=value,
        basis=basis,
        evidence_text=evidence,
        is_ambiguous=ambiguous or not clause_ok,
    )


def _as_other(clause_no: int, evidence: str | None, raw: str) -> RequirementDraft:
    """판정할 수 없는 모양의 조건. 같은 묶음의 다른 조건 판정은 살리고 이 조건만 모름으로 둔다."""
    return RequirementDraft(
        clause_no=clause_no,
        field="other",
        operator="eq",
        value={"text": (evidence or raw or "원문 확인 필요")[:500]},
        basis=None,
        evidence_text=evidence,
        is_ambiguous=True,
    )


def _other_problem(field: str, value: Any) -> str | None:
    if field != "other":
        return None
    if isinstance(value, Mapping) and isinstance(value.get("text"), str) and value["text"].strip():
        return None
    return 'other 값은 {"text": "원문 요약"} 모양이어야 한다'


def _reject_constant(name: str) -> Any:
    raise ValueError(name)


def _finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    if isinstance(value, Mapping):
        return all(_finite(item) for item in value.values())
    return True


def _whole(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)  # JSON 숫자가 3.0으로 오는 경우
    return value if isinstance(value, int) else None


def _known_departments(value: Any, basis: str | None, departments: Sequence[Department]) -> bool:
    names = [value] if isinstance(value, str) else value
    attribute = _LEVEL_ATTRIBUTE.get(basis or "", "")
    if basis not in DEPARTMENT_LEVELS or not isinstance(names, list):
        return False
    known = {getattr(department, attribute) for department in departments}
    return all(name in known for name in names)


def _document(no: int, item: Any, context: Context, notes: _Notes) -> DocumentDraft | None:
    where = f"documents[{no}]"
    name = _text(item.get("name")) if isinstance(item, Mapping) else None
    if not isinstance(item, Mapping) or not name:
        notes.add(f"{where}: name이 있어야 한다", "이름 없는 서류를 버림")
        return None
    required = item.get("is_required", True)
    if not isinstance(required, bool):
        notes.add(f"{where}: is_required는 true나 false여야 한다")
        required = True
    form_url = None
    form_no = item.get("form_attachment_no")
    if form_no is not None:
        number = _whole(form_no)
        attachment = context.attachments.get(number) if number is not None else None
        if attachment is None:
            notes.add(
                f"{where}: form_attachment_no {form_no!r}는 첨부 목록에 없다",
                "없는 첨부를 가리킨 서류 양식 링크를 버림",
            )
        else:
            form_url = attachment.source_url
    return DocumentDraft(name=name[:200], is_required=required, form_url=form_url)


def _moment(
    args: Mapping[str, Any], key: str, default_time: time, notes: _Notes
) -> datetime | None:
    """YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM(KST). 날짜만 있으면 default_time.

    시간대는 붙이지 않게 했다. +09:00이 아닌 시간대가 붙어 있으면 잘못 붙인 것으로 보고 시각만 KST로 읽는다.
    """
    raw = _text(args.get(key))
    if raw is None:
        return None
    try:
        if len(raw) == 10:
            return datetime.combine(date.fromisoformat(raw), default_time, tzinfo=KST)
        moment = datetime.fromisoformat(raw.replace(" ", "T", 1))
    except ValueError:
        notes.add(
            f"{key}는 YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM이어야 한다: {raw!r}",
            f"읽을 수 없는 {key}를 버림",
        )
        return None
    if moment.tzinfo is not None and moment.utcoffset() != timedelta(hours=9):
        notes.add(
            f"{key}에 시간대를 붙이지 말고 KST 시각으로 써라: {raw!r}",
            f"{key}의 시간대를 떼고 KST로 읽음",
        )
    return moment.replace(tzinfo=KST)


def _check_deadline(
    deadline: datetime | None, posted_on: date | None, notes: _Notes
) -> datetime | None:
    """마감 날짜는 판정 기준일이 된다. 게시일과 맞지 않으면 연도를 잘못 읽은 것으로 보고 버린다."""
    if deadline is None or posted_on is None:
        return deadline
    day = deadline.astimezone(KST).date()
    if day < posted_on:
        notes.add(
            f"deadline({day})이 게시일({posted_on})보다 앞선다. 연도를 확인해라",
            "게시일보다 앞선 마감을 버림",
        )
        return None
    if day > posted_on + _DEADLINE_AFTER_POSTED:
        notes.add(
            f"deadline({day})이 게시일({posted_on})보다 1년 넘게 뒤다. 연도를 확인해라",
            "게시일보다 1년 넘게 뒤인 마감을 버림",
        )
        return None
    return deadline


def _basis_date(args: Mapping[str, Any], posted_on: date | None, notes: _Notes) -> date | None:
    key = "eligibility_basis_date"
    raw = _text(args.get(key))
    if raw is None:
        return None
    try:
        day = date.fromisoformat(raw[:10])
    except ValueError:
        notes.add(f"{key}는 YYYY-MM-DD여야 한다: {raw!r}", f"읽을 수 없는 {key}를 버림")
        return None
    if posted_on and not (
        posted_on - _BASIS_BEFORE_POSTED <= day <= posted_on + _BASIS_AFTER_POSTED
    ):
        notes.add(
            f"{key}({day})가 게시일({posted_on})과 너무 멀다. 연도를 확인해라",
            "게시일과 동떨어진 판정 기준일을 버림",
        )
        return None
    return day


def _confidence(raw: Any, notes: _Notes) -> Decimal:
    try:
        if isinstance(raw, bool):
            raise TypeError
        value = Decimal(str(raw))
        if not Decimal(0) <= value <= Decimal(1):
            raise ValueError
    except (TypeError, ValueError, InvalidOperation):
        notes.add(f"confidence는 0–1 사이 숫자여야 한다: {raw!r}", "신뢰도를 읽을 수 없음")
        return Decimal("0.50")
    return value.quantize(Decimal("0.01"))


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
