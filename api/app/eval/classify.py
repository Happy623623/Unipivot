"""공지 분류 평가 세트 EV-CLASSIFY(오케스트레이션 명세 v1 7.1·7.3, O3).

과목 공지에 사람이 단 정답(네 갈래 + 일정 변경이면 바뀐 날)과 분류 엔진(`classify.announcement`)의 답을 견준다.
api 폴더에서 실행한다.

    uv run python -m app.eval.classify --template 공지.json > 정답.json         # 라벨링할 틀(정답 칸이 빈다)
    uv run python -m app.eval.classify 정답.json --record 녹화.json --md 결과.md  # 실제 모델(설정의 classify_model)
    uv run python -m app.eval.classify 정답.json --replay 녹화.json             # 녹화한 답으로(모델을 부르지 않는다)

- 공지 목록(--template의 입력)은 DB에서 뽑은 JSON 배열이다: [{"id", "title", "message", "posted_at"}, …]
- 정답 파일: {"set": "EV-CLASSIFY", "items": [{"id", "title", "body", "posted_on",
  "expected": {"category", "change_date"}}]}. category는 schedule_change·material·opportunity·general이고,
  change_date는 일정 변경일 때만 적는다(YYYY-MM-DD, 공지에 날이 없으면 null)
- --model: 부를 모델(기본은 설정의 classify_model). 모델만 바꿔 같은 정답과 견준다
- --record: 모델 답(갈래·바뀐 날·종류)을 녹화한다. --replay로 같은 답을 다시 셈한다(모델을 부르지 않는다 — 셈을 고친 뒤
  돈 들이지 않고 다시 본다)
- 재는 것: 4×4 혼동행렬, 정확도, **기회성 재현율**(놓치면 공고가 생기지 않는다), 바뀐 날 일치율, 제출 없음(모델이 갈래를
  내지 않아 general로 둔 수), 비용·응답시간
- 합격선(명세 v1 7.3): 기회성 재현율 ≥ 0.9. 못 넘거나 정답에 기회성 공지가 없어 잴 수 없으면 종료 코드 1이다.
  정확도는 지난 결과와 견준다(−5%p 안 — 사람이 본다)

공지 글은 교수가 쓴 글이라 공지 목록·정답·녹화·결과 파일 모두 레포에 넣지 않는다. 녹화와 결과 파일에는 공지 글과
모델의 한 줄 요약을 남기지 않는다(번호·갈래·날짜·토큰·비용만).
"""

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.eligibility import KST
from app.engines import ENGINES
from app.eval.compare_metrics import percentile
from app.eval.fakes import RecordedLlm, tool_reply
from app.llm import LlmClient
from app.lms.classify import CATEGORY_LABELS, SUBMIT, classify
from app.pricing import cost_usd
from app.runtime import event_loop_factory, utf8_output

SET = "EV-CLASSIFY"
ENGINE = "classify.announcement"
CATEGORIES: tuple[str, ...] = tuple(CATEGORY_LABELS)  # 혼동행렬의 줄·칸 순서
OPPORTUNITY = "opportunity"
SCHEDULE_CHANGE = "schedule_change"
RECALL_GATE = 0.9  # 명세 v1 7.3 — 기회성 재현율 ≥ 0.9


class SetError(ValueError):
    """정답·녹화 파일을 읽지 못했다. 무엇을 고칠지 알려 주는 문구다."""


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    body: str | None
    posted_on: date | None
    category: str  # 사람이 단 갈래
    change_date: date | None  # 사람이 단 바뀐 날(일정 변경일 때만)


@dataclass(frozen=True)
class Outcome:
    id: str
    expected: str
    actual: str
    expected_date: date | None
    actual_date: date | None
    submitted: bool
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    # 녹화할 모델 답(갈래·종류·바뀐 날, 요약은 뺀다). 제출이 없으면 None
    reply: dict[str, Any] | None


@dataclass(frozen=True)
class Score:
    items: int
    correct: int
    accuracy: float
    matrix: dict[str, dict[str, int]]  # 정답 갈래 → 엔진 갈래 → 수
    opportunities: int  # 정답이 기회성인 공지
    found_opportunities: int  # 그중 엔진도 기회성으로 본 것
    opportunity_recall: float | None  # 정답에 기회성이 없으면 None(잴 수 없다)
    dates: int  # 정답에 바뀐 날이 있는 일정 변경 공지
    dates_matched: int  # 그중 엔진도 일정 변경이고 같은 날을 낸 것
    date_match_rate: float | None
    no_submission: int
    cost_usd: float
    p50_ms: int
    p95_ms: int

    @property
    def failures(self) -> list[str]:
        """합격선(명세 v1 7.3)을 못 넘은 이유. 비면 통과다."""
        if self.opportunity_recall is None:
            return ["정답에 기회성 공지가 없어 기회성 재현율을 잴 수 없어요"]
        if self.opportunity_recall < RECALL_GATE:
            return [f"기회성 재현율 {self.opportunity_recall:.2f} < {RECALL_GATE}"]
        return []


# ── 파일 ────────────────────────────────────────────────────────────────


def load_set(path: Path) -> list[Item]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("set") != SET
        or not isinstance(data.get("items"), list)
    ):
        raise SetError(f'정답 파일 맨 위는 {{"set": "{SET}", "items": [...]}} 이어야 해요: {path}')
    items = [_item(raw, index) for index, raw in enumerate(data["items"], 1)]
    seen = [item.id for item in items]
    if len(set(seen)) != len(seen):
        raise SetError("번호(id)가 겹치는 공지가 있어요")
    return items


def _item(raw: Any, index: int) -> Item:
    where = f"{index}번째 공지"
    if not isinstance(raw, dict) or not isinstance(raw.get("expected"), dict):
        raise SetError(f"{where}: id·title·body·posted_on·expected가 있어야 해요")
    expected = raw["expected"]
    category = expected.get("category")
    if category not in CATEGORIES:
        raise SetError(
            f"{where}({raw.get('id')}): 정답 갈래가 {', '.join(CATEGORIES)} 중 하나가 아니에요"
        )
    change_date = _day(expected.get("change_date"), f"{where} change_date")
    if change_date is not None and category != SCHEDULE_CHANGE:
        raise SetError(f"{where}({raw.get('id')}): 바뀐 날은 일정 변경 공지에만 적어요")
    return Item(
        id=str(raw.get("id") or index),
        title=str(raw.get("title") or ""),
        body=raw.get("body") or None,
        posted_on=_day(raw.get("posted_on"), f"{where} posted_on"),
        category=category,
        change_date=change_date,
    )


def _day(value: Any, what: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise SetError(f"{what}: 날짜는 YYYY-MM-DD예요({value!r})") from exc


def template(announcements: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """DB에서 뽑은 공지 목록 → 라벨링할 정답 틀. 정답 칸은 비워 둔다(엔진 답을 미리 채우면 그쪽으로 기운다)."""
    items = []
    for one in announcements:
        posted = one.get("posted_at")
        posted_on = datetime.fromisoformat(str(posted)).astimezone(KST).date() if posted else None
        items.append(
            {
                "id": str(one["id"]),
                "title": one.get("title") or "",
                "body": one.get("message") or None,
                "posted_on": posted_on.isoformat() if posted_on else None,
                "expected": {"category": "", "change_date": None},
            }
        )
    return {"set": SET, "items": items}


def replies_of(outcomes: Sequence[Outcome], model: str) -> dict[str, Any]:
    """녹화 파일. 공지 번호 → 모델 답(갈래·바뀐 날·종류), 제출이 없었으면 null."""
    return {"set": SET, "model": model, "replies": {one.id: one.reply for one in outcomes}}


def replay_llm(path: Path, items: Sequence[Item]) -> tuple[RecordedLlm, str]:
    """녹화한 답을 정답 파일의 순서대로 돌려주는 모델. 녹화에 없는 공지가 있으면 SetError다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    replies = data.get("replies") if isinstance(data, dict) else None
    if not isinstance(replies, dict) or not isinstance(data.get("model"), str):
        raise SetError(f'녹화 파일 맨 위는 {{"model": …, "replies": {{…}}}} 이어야 해요: {path}')
    missing = [item.id for item in items if item.id not in replies]
    if missing:
        raise SetError(f"녹화에 없는 공지가 있어요: {', '.join(missing[:5])}")
    answers = [
        tool_reply(SUBMIT, **replies[item.id]) if replies[item.id] else "갈래를 고르지 못했어요."
        for item in items
    ]
    return RecordedLlm(*answers), data["model"]


# ── 돌리기·셈 ─────────────────────────────────────────────────────────────


async def run_set(
    llm: LlmClient, model: str, items: Sequence[Item], *, priced_on: date | None
) -> list[Outcome]:
    """공지마다 분류 엔진을 한 번 부른다(앱과 같은 함수). priced_on이 없으면 비용을 세지 않는다(녹화 답)."""
    outcomes = []
    for item in items:
        started = time.perf_counter()
        result = await classify(
            llm, model=model, title=item.title, body=item.body, posted_on=item.posted_on
        )
        usage = result.reply.usage
        cost = (
            float(cost_usd(llm.provider, model, usage.input_tokens, usage.output_tokens, priced_on))
            if priced_on
            else 0.0
        )
        reply = (
            {
                "category": result.category,
                "opportunity_category": result.opportunity_category,
                "change_date": result.change_date.isoformat() if result.change_date else None,
                "change_kind": result.change_kind,
            }
            if result.submitted
            else None
        )
        outcomes.append(
            Outcome(
                id=item.id,
                expected=item.category,
                actual=result.category,
                expected_date=item.change_date,
                actual_date=result.change_date,
                submitted=result.submitted,
                latency_ms=int((time.perf_counter() - started) * 1000),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=cost,
                reply=reply,
            )
        )
    return outcomes


def score(outcomes: Sequence[Outcome]) -> Score:
    matrix = {expected: dict.fromkeys(CATEGORIES, 0) for expected in CATEGORIES}
    for one in outcomes:
        matrix[one.expected][one.actual] += 1
    correct = sum(matrix[category][category] for category in CATEGORIES)
    opportunities = sum(matrix[OPPORTUNITY].values())
    found = matrix[OPPORTUNITY][OPPORTUNITY]
    dated = [one for one in outcomes if one.expected == SCHEDULE_CHANGE and one.expected_date]
    matched = [
        one
        for one in dated
        if one.actual == SCHEDULE_CHANGE and one.actual_date == one.expected_date
    ]
    latencies = [one.latency_ms for one in outcomes]
    return Score(
        items=len(outcomes),
        correct=correct,
        accuracy=_ratio(correct, len(outcomes)) or 0.0,
        matrix=matrix,
        opportunities=opportunities,
        found_opportunities=found,
        opportunity_recall=_ratio(found, opportunities),
        dates=len(dated),
        dates_matched=len(matched),
        date_match_rate=_ratio(len(matched), len(dated)),
        no_submission=sum(1 for one in outcomes if not one.submitted),
        cost_usd=round(sum(one.cost_usd for one in outcomes), 6),
        p50_ms=int(percentile(latencies, 0.5) or 0),
        p95_ms=int(percentile(latencies, 0.95) or 0),
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


# ── 보고 ────────────────────────────────────────────────────────────────


def markdown(found: Score, *, model: str, on: date, recorded: bool) -> str:
    """결과 표(베이스라인 문서의 엔진별 절에 옮길 한 줄 포함). 공지 글은 넣지 않는다."""
    version = ENGINES[ENGINE].version
    source = "녹화한 답" if recorded else "실제 모델"
    lines = [
        f"## {SET} — {on.isoformat()} · `{ENGINE}` v{version} · `{model}` ({source}) · 공지 {found.items}건",
        "",
        "| 정답 ＼ 엔진 | " + " | ".join(CATEGORIES) + " | 합 |",
        "| --- |" + " --- |" * (len(CATEGORIES) + 1),
    ]
    for expected in CATEGORIES:
        row = found.matrix[expected]
        cells = " | ".join(str(row[actual]) for actual in CATEGORIES)
        lines.append(f"| **{expected}** | {cells} | {sum(row.values())} |")
    lines += [
        "",
        "| 값 | 결과 | 합격선 |",
        "| --- | --- | --- |",
        f"| 정확도 | {_shown(found.accuracy)} ({found.correct}/{found.items}) | 지난 결과 −5%p 안 |",
        f"| 기회성 재현율 | {_shown(found.opportunity_recall)}"
        f" ({found.found_opportunities}/{found.opportunities}) | ≥ {RECALL_GATE} |",
        f"| 바뀐 날 일치율 | {_shown(found.date_match_rate)} ({found.dates_matched}/{found.dates}) | — |",
        f"| 제출 없음 | {found.no_submission} | — |",
        f"| 비용 | ${found.cost_usd:.6f}" + (" (녹화라 세지 않음)" if recorded else "") + " | — |",
        f"| p50 / p95 | {found.p50_ms}ms / {found.p95_ms}ms | — |",
        "",
        "베이스라인 엔진별 절에 옮길 줄:",
        "",
        f"| {ENGINE} | {version} | {model} | {SET} | {on.isoformat()} | 정확도 {_shown(found.accuracy)}"
        f" · 기회성 재현율 {_shown(found.opportunity_recall)} · 바뀐 날 {_shown(found.date_match_rate)}"
        f" · 제출 없음 {found.no_submission} | {found.items}건 |",
    ]
    verdict = "통과" if not found.failures else "실패: " + "; ".join(found.failures)
    lines += ["", f"합격선: **{verdict}**"]
    return "\n".join(lines) + "\n"


def _shown(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def result_json(
    found: Score, outcomes: Sequence[Outcome], *, model: str, on: date
) -> dict[str, Any]:
    """결과 파일. 공지 번호·갈래·날짜·토큰·비용만 남긴다(공지 글과 요약은 남기지 않는다)."""
    return {
        "set": SET,
        "engine": ENGINE,
        "version": ENGINES[ENGINE].version,
        "model": model,
        "on": on.isoformat(),
        "score": {**asdict(found), "failures": found.failures},
        "items": [
            {
                **{key: value for key, value in asdict(one).items() if key != "reply"},
                "expected_date": one.expected_date.isoformat() if one.expected_date else None,
                "actual_date": one.actual_date.isoformat() if one.actual_date else None,
            }
            for one in outcomes
        ],
    }


# ── 명령 ────────────────────────────────────────────────────────────────


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.eval.classify",
        description="공지 분류 엔진을 사람이 단 정답과 견준다(EV-CLASSIFY)",
    )
    parser.add_argument("answers", nargs="?", help="정답 파일(JSON)")
    parser.add_argument("--template", help="DB에서 뽑은 공지 목록(JSON) → 정답 틀을 화면에 찍는다")
    parser.add_argument("--model", help="부를 모델. 없으면 설정의 classify_model")
    parser.add_argument("--replay", help="녹화한 답으로 셈한다(모델을 부르지 않는다)")
    parser.add_argument("--record", help="모델 답을 녹화할 파일")
    parser.add_argument("--out", help="결과 JSON을 적을 파일")
    parser.add_argument("--md", help="결과 표(마크다운)를 적을 파일")
    return parser.parse_args(argv)


async def main(argv: Sequence[str], *, today: date | None = None) -> int:
    args = parse_args(argv)
    on = today or datetime.now(KST).date()
    try:
        if args.template:
            listed = json.loads(Path(args.template).read_text(encoding="utf-8"))
            print(json.dumps(template(listed), ensure_ascii=False, indent=2))
            return 0
        if not args.answers:
            print("정답 파일을 주세요(라벨링할 틀은 --template).", file=sys.stderr)
            return 2
        items = load_set(Path(args.answers))
        if args.replay:
            llm, model = replay_llm(Path(args.replay), items)
            priced_on = None
        else:
            settings = Settings()
            if not settings.google_cloud_project:
                print(
                    "GOOGLE_CLOUD_PROJECT가 없어 모델을 부를 수 없어요(api/.env).", file=sys.stderr
                )
                return 2
            llm, model, priced_on = _gemini(settings), args.model or settings.classify_model, on
    except (OSError, SetError, json.JSONDecodeError, KeyError) as exc:
        print(f"읽지 못했어요: {exc}", file=sys.stderr)
        return 2
    outcomes = await run_set(llm, model, items, priced_on=priced_on)
    if args.record:  # 셈보다 먼저 적는다 — 셈이 실패해도 돈 들인 답은 남는다
        _write(Path(args.record), replies_of(outcomes, model))
    found = score(outcomes)
    report = markdown(found, model=model, on=on, recorded=bool(args.replay))
    print(report)
    if args.out:
        _write(Path(args.out), result_json(found, outcomes, model=model, on=on))
    if args.md:
        Path(args.md).write_text(report, encoding="utf-8")
    return 1 if found.failures else 0


def _write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _gemini(settings: Settings) -> LlmClient:
    from app.llm.gemini import GeminiClient

    return GeminiClient(
        project=settings.google_cloud_project, location=settings.google_cloud_location
    )


if __name__ == "__main__":
    utf8_output()  # 출력을 파이프로 보낼 때 cp949에 없는 글자에서 멈추지 않게(Windows)
    sys.exit(asyncio.run(main(sys.argv[1:]), loop_factory=event_loop_factory()))
