"""시나리오를 돌려 성공률·응답시간·비용을 찍는다(PRD 8장). api 폴더에서 실행한다.

    uv run python -m app.eval.cli --list                      # 시나리오 목록
    uv run python -m app.eval.cli                             # 전부 돌린다
    uv run python -m app.eval.cli --scenarios S01,S13         # 몇 개만
    uv run python -m app.eval.cli --now 2026-10-12T09:00+09:00 --out eval_baseline.json

DATABASE_URL이 필요하고(api/.env), **시험용 DB**여야 한다. 시나리오는 사용자·공고를 만들고 지우므로
실제 Supabase DB 주소면 시작하지 않는다. 모델·Google 캘린더·파일 저장소는 녹화한 응답을 쓴다(명세
12장 `fixtures: "recorded"`) — 네트워크를 쓰지 않는다. LMS는 아직 시나리오가 없어 끼우지 않는다.

W6 베이스라인은 `--out`으로 적어 두고, W9–10 개선을 그 값과 비교한다. 비용은 **돌린 날의 단가**로
계산하므로(결과의 priced_on) 단가가 바뀐 뒤에는 비용끼리 비교하지 않는다.
"""

import argparse
import asyncio
import json
import logging
import sys
import unicodedata
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import psycopg

from app.config import Settings
from app.eligibility import KST
from app.eval.models import Report
from app.eval.runner import run_scenarios
from app.eval.scenarios import SCENARIOS, pick
from app.eval.world import DEFAULT_NOW, managed_database
from app.runtime import event_loop_factory, utf8_output

RESULT = {True: "통과", False: "실패"}


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.eval.cli",
        description="테스트 시나리오를 돌려 성공률·응답시간·비용을 잰다",
    )
    parser.add_argument("--list", action="store_true", help="시나리오 목록만 보여 준다")
    parser.add_argument("--scenarios", help="돌릴 번호(쉼표). 없으면 전부 (예: S01,S13)")
    parser.add_argument(
        "--now", help=f"고정할 현재 시각(ISO 8601). 없으면 {DEFAULT_NOW.isoformat()}"
    )
    parser.add_argument("--out", help="결과 JSON을 적을 파일(베이스라인 저장)")
    return parser.parse_args(argv)


async def main(argv: Sequence[str]) -> int:
    # 결과 표만 보이게 한다. 앱이 깔아 둔 info 로그 중 바깥 호출 한 줄씩은 여기서 끈다
    # (서버에서는 그대로 남긴다 — 키를 가려 적는 것을 시험이 지키고 있다)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = parse_args(argv)
    if args.list:
        for scenario in SCENARIOS:
            print(f"{scenario.code} [{scenario.priority}] {scenario.title}")
        return 0
    try:
        scenarios = pick(_codes(args.scenarios))
        now = _moment(args.now)
    except (KeyError, ValueError) as exc:
        print(str(exc).strip("'"))
        return 1
    database_url = Settings().database_url
    if not database_url:
        print("DATABASE_URL이 없어요(api/.env). 시험용 DB 주소를 넣어 주세요")
        return 1
    if problem := managed_database(database_url):
        print(problem)
        return 1

    print(
        f"시나리오 {len(scenarios)}개를 {now.astimezone(KST):%Y-%m-%d %H:%M} KST 시계로 돌려요."
        " 모델·Google·파일 저장소는 녹화한 응답이에요",
        flush=True,
    )
    try:
        report = await run_scenarios(database_url, scenarios, now=now)
    except psycopg.OperationalError as exc:
        print(f"DB에 연결하지 못했어요: {exc}")
        return 1
    _print(report)
    if args.out:
        path = Path(args.out)
        path.write_text(
            json.dumps(report.json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"결과를 적었어요: {path}")
    return 0 if report.passed == report.total else 1


def _print(report: Report) -> None:
    print()
    print(_row("번호", "결과", "확인", "응답시간", "비용(USD)", "시나리오"))
    for result in report.results:
        print(
            _row(
                result.code,
                RESULT[result.ok],
                str(len(result.checks)),
                f"{result.latency_ms}ms",
                f"{float(result.cost_usd):.6f}",
                result.title,
            )
        )
        if result.error:
            print(f"      └ {result.error}")
    rate = f"{report.success_rate * 100:.1f}%"
    print()
    print(
        f"통과 {report.passed}/{report.total}({rate}) ·"
        f" 응답시간 p50 {report.p50}ms · p95 {report.p95}ms ·"
        f" 그중 엔드포인트가 쓴 시간 합 {report.api_ms:.0f}ms ·"
        f" 비용 {float(report.cost_usd):.6f} USD({report.priced_on} 단가) ·"
        f" LLM 호출 {report.llm_calls}회"
    )
    print("실행 기록: agent_runs의 trigger_type = 'eval', scenario_code로 남았어요")


def _row(code: str, result: str, checks: str, latency: str, cost: str, title: str) -> str:
    """표 한 줄. 한글은 두 칸을 차지하므로 글자 수가 아니라 보이는 너비로 맞춘다."""
    return "  ".join(
        (
            _cell(code, 4),
            _cell(result, 4),
            _cell(checks, 4, right=True),
            _cell(latency, 8, right=True),
            _cell(cost, 9, right=True),
            title,
        )
    )


def _cell(text: str, width: int, *, right: bool = False) -> str:
    gap = " " * max(width - _width(text), 0)
    return gap + text if right else text + gap


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _codes(raw: str | None) -> list[str] | None:
    """--scenarios. 주지 않으면 None(전부), 쉼표만 적었으면 빈 목록이라 pick이 거절한다."""
    if raw is None:
        return None
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def _moment(raw: str | None) -> datetime:
    """--now. 시간대를 적지 않으면 KST로 본다."""
    if not raw:
        return DEFAULT_NOW
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"--now를 읽지 못했어요: {raw} (예: 2026-10-12T09:00:00+09:00)") from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=KST)


if __name__ == "__main__":
    utf8_output()  # 출력을 파이프로 보낼 때 cp949에 없는 글자에서 멈추지 않게(Windows)
    sys.exit(asyncio.run(main(sys.argv[1:]), loop_factory=event_loop_factory()))
