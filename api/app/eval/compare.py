"""모델 비교 실험(docs/LLM_모델_선정.md "비교 실험"): 같은 공고·포스터를 모델마다 돌려 정확도·비용·응답시간을 견준다.

실제 Gemini를 부른다(체험 크레딧, 목록 단가로 셈만 한다). api 폴더에서 실행한다.

    uv run python -m app.eval.compare <저장한 공지 폴더…> --posters <포스터 폴더> --out compare.json --md compare.md

- 공지는 `app.crawl` 가져오기와 같은 저장 폴더다(페이지 + 첨부). 포스터 폴더는 JPG·PNG·WEBP·PDF 파일들이다
- --models: 비교할 모델(쉼표, 기본 gemini-3.8-flash,gemini-3.5-flash-lite). 요건 추출의 글·첨부 이미지와 포스터 모두
  이 모델로 바꾼다. 프롬프트·도구·스키마·첨부 글자 뽑기는 같다
- --answers: 정답(JSON). 있으면 정답과, 없으면 첫 모델과 견준다. --template로 첫 모델 결과를 정답 틀로 쓴다
- --profiles: 가상 프로필(JSON 목록). 없으면 아래 PROFILES 다섯을 쓴다. 판정 혼동행렬에 쓴다
- --db: 학과 목록을 DATABASE_URL에서 읽고, 실행 로그를 agent_runs·llm_calls에 trigger=eval로 남긴다
  (scenario_code `CMP-<모델 약자>-<번호>`). 실제 Supabase DB에는 쓰지 않는다. 없으면 화면에만 셈한다
- --repeat: 같은 것을 몇 번 돌릴지(응답시간 흔들림을 보려면 3 이상). 정확도는 첫 번째 실행으로만 센다.
  항목마다 모델을 번갈아 돌린다(시간대에 따른 흔들림이 한 모델에 몰리지 않게)
- --today: 포스터를 올린 날(포스터의 연도 없는 날짜·지난 날짜를 이 날로 가린다)이자, 기준일·마감일·게시일이
  모두 없는 공지의 판정 기준일(앱도 오늘로 판정한다). 같은 자료로 다시 잴 때 고정한다

공고 글은 모델에만 보내고 결과 파일에는 요건·마감일·토큰·비용만 남긴다(근거 문장도 남기지 않는다). 결과 파일은
레포에 넣지 않는다. 모델 실행이 끝나면 결과를 먼저 쓰고 셈을 한다 — 셈이 실패해도 돈 들인 실행은 남는다.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, nullcontext
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.config import Settings
from app.crawl.saved import load_folder, notice_folders
from app.eligibility import KST, Department, Profile, to_kst_date
from app.eval.compare_metrics import Confusion, Match, conditions, judge, percentile
from app.eval.world import managed_database
from app.extraction.agent import ExtractionAgent
from app.extraction.models import NoticeInput
from app.extraction.prompt import SUBMIT
from app.extraction.setup import build_agent
from app.llm import Blob, LlmClient
from app.posters.extract import LOW_CONFIDENCE
from app.posters.extract import extract as extract_poster
from app.pricing import PRICES, cost_usd
from app.runtime import event_loop_factory, utf8_output
from app.uploads import sniff

DEFAULT_MODELS = ("gemini-3.8-flash", "gemini-3.5-flash-lite")
SHORT = {"gemini-3.8-flash": "F38", "gemini-3.5-flash-lite": "FL35"}
POSTER_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
REQUIREMENT_KEYS = ("clause_no", "field", "operator", "value", "basis", "is_ambiguous")
# 가상 프로필(PRD 정답셋 규칙: 경계값 포함). --profiles로 바꾼다. 날짜는 판정 기준일과 견주므로 고정해 둔다
PROFILES: list[dict[str, Any]] = [
    {
        "name": "학부 3학년 평점 3.00",
        "department": "인공지능학과",
        "degree_program": "bachelor",
        "grade": 3,
        "enrollment_status": "enrolled",
        "semesters_completed": 4,
        "credits_last_semester": 18,
        "gpa_last_semester": 3.0,
        "gpa_total": 3.0,
        "birth_date": "2004-03-01",
        "region_sido": "경기도",
        "region_sigungu": "안산시",
        "income_bracket": 4,
    },
    {
        "name": "학부 1학년 신입생",
        "department": "경영학부",
        "degree_program": "bachelor",
        "grade": 1,
        "enrollment_status": "enrolled",
        "semesters_completed": 0,
        "birth_date": "2007-05-10",
        "region_sido": "서울특별시",
        "region_sigungu": "강남구",
    },
    {
        "name": "휴학생 평점 4.2",
        "department": "기계공학과",
        "degree_program": "bachelor",
        "grade": 2,
        "enrollment_status": "on_leave",
        "semesters_completed": 3,
        "credits_last_semester": 15,
        "gpa_last_semester": 4.2,
        "gpa_total": 4.0,
        "birth_date": "2003-08-20",
        "income_bracket": 8,
    },
    {
        "name": "석사 과정",
        "department": "인공지능학과",
        "degree_program": "master",
        "grade": 1,
        "enrollment_status": "enrolled",
        "semesters_completed": 1,
        "gpa_total": 4.3,
        "birth_date": "1999-01-15",
    },
    {
        "name": "학부 4학년 만 34세 마지막 해",
        "department": "융합디자인학부",
        "degree_program": "bachelor",
        "grade": 4,
        "enrollment_status": "enrolled",
        "semesters_completed": 7,
        "credits_last_semester": 12,
        "gpa_last_semester": 2.9,
        "birth_date": "1992-01-01",
        "region_sido": "경기도",
        "region_sigungu": "수원시",
        "welfare_status": "basic_livelihood",
    },
]


@dataclass
class Collector:
    """한 실행의 도구·모델 호출을 센다(RunLog 대역). --db면 실제 기록(inner)에도 그대로 넘긴다."""

    inner: Any = None
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = Decimal(0)
    tools: dict[str, int] = field(default_factory=dict)

    @asynccontextmanager
    async def tool(self, name: str, input: dict[str, Any] | None = None) -> AsyncIterator[Any]:
        self.tools[name] = self.tools.get(name, 0) + 1
        if self.inner is None:
            yield _Call()
            return
        async with self.inner.tool(name, input) as call:
            yield call

    async def record_llm(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        tool_call: Any = None,
    ) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost += cost_usd(
            provider, model, input_tokens, output_tokens, datetime.now(KST).date()
        )
        if self.inner is not None:
            await self.inner.record_llm(
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                tool_call=tool_call,
            )


@dataclass
class _Call:
    id: str = "compare"
    output: Any = None


@dataclass
class Outcome:
    """한 모델이 한 항목(공지·포스터)을 한 번 돈 결과. 결과 파일의 한 줄이다."""

    kind: str  # notice · poster
    item: str  # 폴더·파일 이름
    model: str
    attempt: int
    ok: bool
    wall_ms: int
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    submits: int = 0  # 요건 제출 횟수. 2번 이상이면 스키마를 다시 낸 것이다
    needs_review: bool = False
    deadline: str | None = None  # KST 날짜
    title: str | None = None  # 포스터만
    requirements: list[dict[str, Any]] = field(default_factory=list)
    basis: str | None = None  # 판정 기준일(공고 기준일 → 마감일 → 게시일)
    error: str | None = None


AgentFactory = Callable[..., ExtractionAgent]
LogScope = Callable[[str], AbstractAsyncContextManager[Any]]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="요건 추출·포스터 추출 모델 비교")
    parser.add_argument("folders", nargs="*", type=Path, help="저장한 공지 폴더(여럿)")
    parser.add_argument("--posters", type=Path, help="포스터 파일이 든 폴더")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--answers", type=Path, help="정답 JSON(없으면 첫 모델과 견준다)")
    parser.add_argument("--template", type=Path, help="첫 모델 결과로 정답 틀을 써 둘 파일")
    parser.add_argument("--profiles", type=Path, help="가상 프로필 JSON 목록")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        help="포스터를 올린 날로 볼 날짜 YYYY-MM-DD(기본: 오늘 KST)",
    )
    parser.add_argument(
        "--db", action="store_true", help="학과 목록을 읽고 실행 로그를 DB에 남긴다"
    )
    parser.add_argument("--out", type=Path, default=Path("compare.json"))
    parser.add_argument("--md", type=Path, help="요약 표(Markdown)를 쓸 파일")
    args = parser.parse_args(argv)
    if not args.folders and args.posters is None:
        parser.error("공지 폴더나 --posters 중 하나는 있어야 해요")
    if args.repeat < 1:
        parser.error("--repeat는 1 이상이어야 해요")
    priced = {model for _provider, model in PRICES}
    unknown = [one for one in _models(args.models) if one not in priced]
    if unknown:
        parser.error(f"단가표(app/pricing.py)에 없는 모델이에요: {', '.join(unknown)}")
    return args


def _models(text: str) -> list[str]:
    return [one.strip() for one in text.split(",") if one.strip()]


def load_answers(path: Path | None) -> dict[str, Any] | None:
    """정답 파일을 모델을 부르기 전에 읽고 모양을 본다(틀리면 돈 들이기 전에 멈춘다)."""
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    problem = None
    if not isinstance(data, dict):
        problem = '맨 위는 {"notices": {…}, "posters": {…}}여야 해요'
    else:
        for kind in ("notices", "posters"):
            if not isinstance(data.setdefault(kind, {}), dict):
                problem = f"{kind}는 이름 → 정답인 객체여야 해요"
        for name, answer in data["notices"].items() if not problem else ():
            requirements = answer.get("requirements") if isinstance(answer, dict) else None
            if not isinstance(requirements, list) or not all(
                isinstance(one, dict) and "field" in one and "operator" in one
                for one in requirements
            ):
                problem = f"notices[{name}]의 requirements는 field·operator가 있는 목록이어야 해요"
    if problem:
        raise SystemExit(f"정답 파일을 읽지 못했어요: {problem}")
    return data


def load_profiles(path: Path | None) -> list[tuple[str, Profile]]:
    rows = json.loads(path.read_text(encoding="utf-8")) if path else PROFILES
    found = []
    for row in rows:
        values = {key: value for key, value in row.items() if key != "name"}
        if isinstance(values.get("birth_date"), str):
            values["birth_date"] = date.fromisoformat(values["birth_date"])
        found.append((str(row.get("name", f"프로필 {len(found) + 1}")), Profile(**values)))
    return found


def _requirements(items: Sequence[Any]) -> list[dict[str, Any]]:
    """비교에 쓰는 칸만 남긴다(근거 문장 같은 원문은 결과 파일에 남기지 않는다)."""
    return [
        {
            key: (one.get(key) if isinstance(one, dict) else getattr(one, key, None))
            for key in REQUIREMENT_KEYS
        }
        for one in items
    ]


async def run_notice(
    agent: ExtractionAgent,
    notice: NoticeInput,
    log: Collector,
    *,
    item: str,
    attempt: int,
    today: date,
) -> Outcome:
    started = time.perf_counter()
    try:
        result = await agent.run(notice, log)
    except Exception as exc:  # 한 공고가 실패해도 비교는 이어 간다
        return _outcome("notice", item, agent.model, attempt, started, log, error=repr(exc)[:200])
    deadline = to_kst_date(result.deadline_at) if result.deadline_at else None
    basis = result.eligibility_basis_date or deadline or notice.posted_on or today
    return _outcome(
        "notice",
        item,
        agent.model,
        attempt,
        started,
        log,
        ok=result.succeeded,
        needs_review=result.needs_review,
        deadline=deadline.isoformat() if deadline else None,
        requirements=_requirements(result.requirements),
        basis=basis.isoformat(),
    )


async def run_poster(
    llm: LlmClient,
    model: str,
    path: Path,
    log: Collector,
    *,
    departments: Sequence[Department],
    attempt: int,
    today: date,
) -> Outcome:
    started = time.perf_counter()
    data = path.read_bytes()
    found = sniff(data)
    item = path.name
    if found is None:
        return _outcome("poster", item, model, attempt, started, log, error="형식을 모르는 파일")
    try:
        async with log.tool("extract_from_poster", {"file": item}) as call:
            extracted = await extract_poster(
                llm,
                model=model,
                blob=Blob(data=data, mime_type=found.mime),
                departments=departments,
                today=today,
            )
            await log.record_llm(
                provider=llm.provider,
                model=model,
                input_tokens=extracted.reply.usage.input_tokens,
                output_tokens=extracted.reply.usage.output_tokens,
                latency_ms=extracted.reply.latency_ms,
                tool_call=call,
            )
            call.output = {"title": extracted.draft.title}
    except Exception as exc:
        return _outcome("poster", item, model, attempt, started, log, error=repr(exc)[:200])
    draft = extracted.draft
    deadline = to_kst_date(draft.deadline_at) if draft.deadline_at else None
    return _outcome(
        "poster",
        item,
        model,
        attempt,
        started,
        log,
        ok=True,
        title=draft.title,
        deadline=deadline.isoformat() if deadline else None,
        requirements=_requirements([one.model_dump(mode="json") for one in draft.requirements]),
        needs_review=draft.extraction_confidence < LOW_CONFIDENCE,  # 앱의 확인 문턱과 같다
    )


def _outcome(
    kind: str, item: str, model: str, attempt: int, started: float, log: Collector, **values: Any
) -> Outcome:
    return Outcome(
        kind=kind,
        item=item,
        model=model,
        attempt=attempt,
        ok=values.pop("ok", False),
        wall_ms=int((time.perf_counter() - started) * 1000),
        llm_calls=log.calls,
        input_tokens=log.input_tokens,
        output_tokens=log.output_tokens,
        cost_usd=float(log.cost),
        submits=log.tools.get(SUBMIT, 0),
        **values,
    )


def _known(requirements: Sequence[Any], needs_review: bool) -> bool:
    """요건을 읽었다고 볼지 — 앱과 같다(요건이 0개인데 원문 확인이 켜져 있으면 못 읽은 것)."""
    return bool(requirements) or not needs_review


def summarize(
    outcomes: Sequence[Outcome],
    models: Sequence[str],
    answers: dict[str, Any] | None,
    profiles: Sequence[tuple[str, Profile]],
    departments: Sequence[Department],
    *,
    today: date,
) -> dict[str, Any]:
    """모델마다 정확도(정답 또는 첫 모델 기준)·비용·응답시간을 셈한다.

    판정은 기준과 비교 모델을 **각자의 기준일**로 한다(기준일·마감일을 잘못 읽은 것도 판정 차이로 보이게).
    """
    first = {(o.kind, o.item, o.model): o for o in outcomes if o.attempt == 1}
    reference_model = models[0]
    rows = {}
    for model in models:
        mine = [o for o in outcomes if o.model == model]
        notices = [o for o in mine if o.kind == "notice" and o.attempt == 1]
        posters = [o for o in mine if o.kind == "poster" and o.attempt == 1]
        match, confusion = Match(), Confusion()
        deadline_same = deadline_total = 0
        for outcome in notices:
            expected = _expected_notice(answers, first, outcome, reference_model)
            if expected is None:
                continue
            match.add(conditions(outcome.requirements), conditions(expected["requirements"]))
            deadline_total += 1
            deadline_same += int(outcome.deadline == expected.get("deadline"))
            mine_basis = outcome.basis or expected.get("basis")
            their_basis = expected.get("basis") or outcome.basis
            reference_known = _known(expected["requirements"], bool(expected.get("needs_review")))
            for _, profile in profiles:
                confusion.add(
                    judge(
                        expected["requirements"],
                        profile,
                        basis=_day(their_basis, today),
                        departments=departments,
                        known=reference_known,
                    ),
                    judge(
                        outcome.requirements,
                        profile,
                        basis=_day(mine_basis, today),
                        departments=departments,
                        known=_known(outcome.requirements, outcome.needs_review),
                    )
                    if outcome.ok
                    else "undetermined",
                )
        poster_title = poster_deadline = poster_total = 0
        for outcome in posters:
            expected = _expected_poster(answers, first, outcome, reference_model)
            if expected is None:
                continue
            poster_total += 1
            poster_title += int(_same_text(outcome.title, expected.get("title")))
            poster_deadline += int(outcome.deadline == expected.get("deadline"))
        notice_runs = [o for o in mine if o.kind == "notice"]
        poster_runs = [o for o in mine if o.kind == "poster"]
        cost = sum(o.cost_usd for o in mine)
        rows[model] = {
            "runs": len(mine),
            "succeeded": sum(o.ok for o in mine),
            "notices": len(notices),
            "posters": len(posters),
            "needs_review": sum(o.needs_review for o in notices),
            "schema_retries": sum(o.submits > 1 for o in notices),
            "precision": match.precision,
            "recall": match.recall,
            "f1": match.f1,
            "jaccard": match.jaccard,
            "deadline_match": _rate(deadline_same, deadline_total),
            "judgments": confusion.total,
            "judgment_agree": _rate(confusion.agree, confusion.total),
            "eligible_to_ineligible": confusion.eligible_to_ineligible,
            "ineligible_to_eligible": confusion.ineligible_to_eligible,
            "confusion": confusion.table(),
            "poster_title_match": _rate(poster_title, poster_total),
            "poster_deadline_match": _rate(poster_deadline, poster_total),
            "cost_usd": round(cost, 6),
            # 실행 한 번의 평균(반복 실행도 한 번씩 센다). 공지와 포스터는 따로 본다
            "cost_per_notice_usd": _mean_cost(notice_runs),
            "cost_per_poster_usd": _mean_cost(poster_runs),
            # 응답시간은 실패한 실행도 넣는다(시간 초과·상한까지 돈 실행이 빠지면 p95가 좋아 보인다)
            "notice_p50_ms": percentile([o.wall_ms for o in notice_runs], 0.5),
            "notice_p95_ms": percentile([o.wall_ms for o in notice_runs], 0.95),
            "poster_p50_ms": percentile([o.wall_ms for o in poster_runs], 0.5),
            "poster_p95_ms": percentile([o.wall_ms for o in poster_runs], 0.95),
        }
    return {
        "reference": "answers" if answers else f"model:{reference_model}",
        "models": rows,
    }


def _day(text: str | None, today: date) -> date:
    return date.fromisoformat(text) if text else today


def _mean_cost(runs: Sequence[Outcome]) -> float | None:
    return round(sum(o.cost_usd for o in runs) / len(runs), 6) if runs else None


def _expected_notice(
    answers: dict[str, Any] | None, first: dict[Any, Outcome], outcome: Outcome, reference: str
) -> dict[str, Any] | None:
    if answers is not None:
        return answers.get("notices", {}).get(outcome.item)
    if outcome.model == reference:
        return None  # 정답이 없으면 첫 모델이 기준이라 자기 자신과는 견주지 않는다
    base = first.get(("notice", outcome.item, reference))
    if base is None or not base.ok:
        return None
    return {
        "requirements": base.requirements,
        "deadline": base.deadline,
        "basis": base.basis,
        "needs_review": base.needs_review,
    }


def _expected_poster(
    answers: dict[str, Any] | None, first: dict[Any, Outcome], outcome: Outcome, reference: str
) -> dict[str, Any] | None:
    if answers is not None:
        return answers.get("posters", {}).get(outcome.item)
    if outcome.model == reference:
        return None
    base = first.get(("poster", outcome.item, reference))
    if base is None or not base.ok:
        return None
    return {"title": base.title, "deadline": base.deadline}


def _same_text(a: str | None, b: str | None) -> bool:
    def norm(text: str | None) -> str:
        return "".join((text or "").split())

    return bool(a) and norm(a) == norm(b)


def _rate(part: int, total: int) -> float | None:
    return part / total if total else None


def template(outcomes: Sequence[Outcome], model: str) -> dict[str, Any]:
    """첫 모델 결과로 만든 정답 틀. 사람이 원문과 대조해 고친 뒤 --answers로 쓴다."""
    notices, posters = {}, {}
    for outcome in outcomes:
        if outcome.model != model or outcome.attempt != 1:
            continue
        if outcome.kind == "notice":
            notices[outcome.item] = {
                "deadline": outcome.deadline,
                "basis": outcome.basis,
                "needs_review": outcome.needs_review,
                "requirements": [
                    {key: one.get(key) for key in REQUIREMENT_KEYS} for one in outcome.requirements
                ],
            }
        else:
            posters[outcome.item] = {"title": outcome.title, "deadline": outcome.deadline}
    return {"notices": notices, "posters": posters}


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def markdown(summary: dict[str, Any]) -> str:
    rows = summary["models"]
    head = [
        f"기준: {'정답' if summary['reference'] == 'answers' else summary['reference'][6:] + '(첫 모델)'}",
        "",
        "| 모델 | 실행 | 성공 | 원문 확인 | 스키마 재제출 | 조건 F1 | 마감일 일치 | 판정 일치 | 적격→부적격 |"
        " 부적격→적격 | 포스터 제목·마감 | 비용(공지·포스터 1건) | 공지 p50 · p95 | 포스터 p50 · p95 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for model, row in rows.items():
        head.append(
            f"| {model} | {row['runs']} | {row['succeeded']} | {row['needs_review']} |"
            f" {row['schema_retries']} | {_pct(row['f1'])} | {_pct(row['deadline_match'])} |"
            f" {_pct(row['judgment_agree'])} | {row['eligible_to_ineligible']} |"
            f" {row['ineligible_to_eligible']} |"
            f" {_pct(row['poster_title_match'])} · {_pct(row['poster_deadline_match'])} |"
            f" {_usd(row['cost_per_notice_usd'])} · {_usd(row['cost_per_poster_usd'])} |"
            f" {_sec(row['notice_p50_ms'])} · {_sec(row['notice_p95_ms'])} |"
            f" {_sec(row['poster_p50_ms'])} · {_sec(row['poster_p95_ms'])} |"
        )
    return "\n".join(head) + "\n"


def _usd(value: float | None) -> str:
    return "-" if value is None else f"${value:.4f}"


def _sec(value: float | None) -> str:
    return "-" if value is None else f"{value / 1000:.1f}초"


async def main(
    argv: Sequence[str],
    *,
    make_agent: AgentFactory = build_agent,
    make_llm: Callable[[Settings], LlmClient] | None = None,
    settings: Settings | None = None,
) -> int:
    args = parse_args(argv)
    settings = settings or Settings()
    models = _models(args.models)
    profiles = load_profiles(args.profiles)
    answers = load_answers(args.answers)
    today = args.today or datetime.now(KST).date()
    folders = notice_folders(args.folders) if args.folders else []
    names = [folder.name for folder in folders]
    if len(set(names)) != len(names):  # 결과·정답은 폴더 이름으로 짝짓는다
        raise SystemExit("이름이 같은 공지 폴더가 있어요. 폴더 이름을 서로 다르게 해 주세요.")
    posters = (
        sorted(p for p in args.posters.iterdir() if p.suffix.lower() in POSTER_SUFFIXES)
        if args.posters
        else []
    )
    notices = [(folder.name, load_folder(folder).notice_input()) for folder in folders]
    outcomes: list[Outcome] = []
    async with _logging(args, settings) as (departments, scope):
        llm = (make_llm or _gemini)(settings) if posters else None
        agents = {
            model: make_agent(
                settings.model_copy(update={"vision_model": model}),
                departments=departments,
                model=model,
            )
            for model in models
        }
        # 항목마다 모델을 번갈아 돈다(시간대에 따라 느려져도 한 모델에만 몰리지 않게)
        for attempt in range(1, args.repeat + 1):
            for number, (item, notice) in enumerate(notices, 1):
                for model in models:
                    code = f"CMP-{SHORT.get(model, model)}-N{number:02d}"
                    outcome = await _logged(
                        scope,
                        code,
                        lambda log, model=model, item=item, notice=notice, attempt=attempt: (
                            run_notice(
                                agents[model], notice, log, item=item, attempt=attempt, today=today
                            )
                        ),
                    )
                    outcomes.append(outcome)
                    _print(outcome)
            for number, path in enumerate(posters, 1):
                for model in models:
                    assert llm is not None
                    code = f"CMP-{SHORT.get(model, model)}-P{number:02d}"
                    outcome = await _logged(
                        scope,
                        code,
                        lambda log, model=model, path=path, attempt=attempt: run_poster(
                            llm,
                            model,
                            path,
                            log,
                            departments=departments,
                            attempt=attempt,
                            today=today,
                        ),
                    )
                    outcomes.append(outcome)
                    _print(outcome)
    result: dict[str, Any] = {
        "priced_on": datetime.now(KST).date().isoformat(),  # 비용은 이 날의 목록 단가다
        "today": today.isoformat(),
        "outcomes": [asdict(one) for one in outcomes],
    }
    _write(args.out, result)  # 셈이 실패해도 돈 들인 실행 결과는 남긴다
    if args.template:
        _write(args.template, template(outcomes, models[0]))
    summary = summarize(outcomes, models, answers, profiles, departments, today=today)
    _write(args.out, {"summary": summary, **result})
    table = markdown(summary)
    print(table)
    if args.md:
        args.md.write_text(table, encoding="utf-8")
    return 0 if outcomes and all(one.ok for one in outcomes) else 1


class _RunFailed(Exception):
    """비교 실행이 실패했다 — --db면 agent_runs에 실패로 남기려고 실행 범위 안에서 던진다."""


async def _logged(scope: LogScope, code: str, work: Callable[[Collector], Any]) -> Outcome:
    """한 번 돌린다. 실패한 실행은 기록(--db)에도 실패로 남는다(지표가 agent_runs에서 나온다)."""
    holder: list[Outcome] = []
    try:
        async with scope(code) as inner:
            outcome = await work(Collector(inner=inner))
            holder.append(outcome)
            if inner is not None and not outcome.ok:
                raise _RunFailed(outcome.error or "요건을 읽지 못했어요")
    except _RunFailed:
        pass
    return holder[0]


def _write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _print(outcome: Outcome) -> None:
    status = "성공" if outcome.ok else f"실패 {outcome.error or ''}"
    print(
        f"{outcome.model} · {outcome.kind} {outcome.item} #{outcome.attempt}: {status}"
        f" · 조건 {len(outcome.requirements)}개 · {outcome.wall_ms / 1000:.1f}초 · ${outcome.cost_usd:.4f}",
        flush=True,
    )


def _gemini(settings: Settings) -> LlmClient:
    from app.llm.gemini import GeminiClient

    return GeminiClient(
        project=settings.google_cloud_project, location=settings.google_cloud_location
    )


@asynccontextmanager
async def _logging(
    args: argparse.Namespace, settings: Settings
) -> AsyncIterator[tuple[list[Department], LogScope]]:
    """--db면 학과 목록을 읽고 실행마다 agent_runs 행을 만든다(trigger=eval). 아니면 기록 없이 센다."""
    if not args.db:
        print(
            "학과 목록 없이 셈해요(--db 없음): 학과 조건은 두 모델 모두 판정하지 못함으로 나와요.",
            file=sys.stderr,
        )
        yield [], lambda _code: nullcontext(None)
        return
    import psycopg
    from psycopg.rows import dict_row

    from app.agent_log import agent_run, using
    from app.extraction.store import load_departments

    host = os.environ.get("PGHOST", "")
    if managed_database(settings.database_url.lower()) or managed_database(host.lower()):
        raise SystemExit(
            "실제 Supabase DB에는 비교 실험을 남기지 않아요. 로컬 시험 DB를 DATABASE_URL에 넣어 주세요."
        )
    async with await psycopg.AsyncConnection.connect(
        settings.database_url, row_factory=dict_row, autocommit=True, prepare_threshold=None
    ) as conn:
        departments = await load_departments(conn)

        def scope(code: str) -> AbstractAsyncContextManager[Any]:
            return agent_run(using(conn), trigger="eval", scenario_code=code)

        yield departments, scope


if __name__ == "__main__":
    utf8_output()
    sys.exit(asyncio.run(main(sys.argv[1:]), loop_factory=event_loop_factory()))
