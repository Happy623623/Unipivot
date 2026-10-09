"""공고 하나로 요건 추출 에이전트를 돌려 본다(실제 Gemini 호출). api 폴더에서 실행한다.

    uv run python -m app.extraction.cli --title "○○장학생 선발" --body 본문.txt --attach 공고문.hwp

- --body: 본문 파일(.txt·.html) 경로나 본문 글자. HTML은 글자로 바꾼다
- --attach: 첨부 파일. 여러 번 쓸 수 있고 쓴 순서가 첨부 번호다
- --url: 원문 주소. 주면 fetch_original(원문 다시 읽기)을 쓸 수 있다
- --model: 모델을 바꿔 비교한다(예: gemini-3.5-flash-lite). 단가표에 있는 ID만 된다
- --db: agent_runs·tool_calls·llm_calls에 trigger=eval로 남긴다(DATABASE_URL 필요). 공고·요건은 저장하지 않는다
도구 호출과 고른 이유, 토큰, 추정 비용(목록 단가)을 찍고 마지막에 결과 JSON을 찍는다.
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.attachments import html_text
from app.config import Settings
from app.crawl import WebFetcher
from app.eligibility import KST
from app.extraction.agent import ExtractionAgent
from app.extraction.models import AttachmentInput, ExtractionResult, NoticeInput
from app.extraction.setup import build_agent
from app.pricing import cost_usd


@dataclass
class _Logged:
    id: str
    output: Any = None


class ConsoleRunLog:
    """RunLog를 화면에 찍는다. 비용은 오늘(KST) 단가로 계산한다."""

    def __init__(self) -> None:
        self.calls = 0
        self.tools = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost = Decimal(0)

    @asynccontextmanager
    async def tool(self, name: str, input: dict[str, Any] | None = None) -> AsyncIterator[_Logged]:
        self.tools += 1
        reason = (input or {}).get("reason")
        print(f"[{self.tools}] {name}" + (f" — {reason}" if reason else ""))
        logged = _Logged(id=f"tool-{self.tools}")
        yield logged
        print(f"    결과: {json.dumps(logged.output, ensure_ascii=False, default=str)[:300]}")

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
        cost = cost_usd(provider, model, input_tokens, output_tokens, datetime.now(KST).date())
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost += cost
        print(
            f"    LLM {model}: 입력 {input_tokens:,} · 출력 {output_tokens:,} 토큰"
            f" · {latency_ms / 1000:.1f}초 · ${cost:.4f}"
        )

    def total(self) -> str:
        return (
            f"합계: LLM {self.calls}번 · 입력 {self.input_tokens:,} · 출력 {self.output_tokens:,} 토큰"
            f" · ${self.cost:.4f} (목록 단가. 체험 크레딧이 있으면 청구는 0원)"
        )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="공고 하나로 요건 추출 에이전트를 돌려 본다")
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", default="", help="본문 파일 경로나 본문 글자")
    parser.add_argument("--attach", action="append", default=[], help="첨부 파일(여러 번)")
    parser.add_argument("--url", help="원문 주소(fetch_original용)")
    parser.add_argument("--posted", type=date.fromisoformat, help="게시일 YYYY-MM-DD(기본: 오늘)")
    parser.add_argument("--model", help="추출 모델(기본: EXTRACTION_MODEL)")
    parser.add_argument("--db", action="store_true", help="실행 로그를 DB에 남긴다(trigger=eval)")
    parser.add_argument("--scenario", help="--db일 때 agent_runs.scenario_code")
    return parser.parse_args(argv)


def load_notice(args: argparse.Namespace) -> NoticeInput:
    body = args.body
    if body and os.path.isfile(body):  # 경로가 아니면(긴 본문 글자 등) 그대로 본문으로 쓴다
        path = Path(body)
        body = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".html", ".htm"):
            body = html_text(body)
    attachments = tuple(
        AttachmentInput(seq, Path(name).name, Path(name).read_bytes())
        for seq, name in enumerate(args.attach, 1)
    )
    return NoticeInput(
        title=args.title,
        body=body,
        posted_on=args.posted or datetime.now(KST).date(),
        original_url=args.url,
        attachments=attachments,
    )


def result_json(result: ExtractionResult) -> str:
    data = asdict(result)
    for attachment in data["attachments"]:
        text = attachment.pop("text")
        attachment["text_chars"] = len(text) if text else 0
    return json.dumps(data, ensure_ascii=False, indent=2, default=_plain)


def _plain(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value))


AgentFactory = Callable[..., ExtractionAgent]


async def main(argv: Sequence[str], *, make_agent: AgentFactory = build_agent) -> int:
    args = parse_args(argv)
    settings = Settings()
    notice = load_notice(args)
    fetcher = WebFetcher() if args.url else None
    try:
        if args.db:
            result = await _run_with_db(args, settings, notice, fetcher, make_agent)
        else:
            agent = make_agent(settings, fetch_page=fetcher, model=args.model)
            console = ConsoleRunLog()
            print(f"모델 {agent.model} · 첨부 {len(notice.attachments)}개")
            result = await agent.run(notice, console)
            print(console.total())
    finally:
        if fetcher is not None:
            await fetcher.aclose()
    print(result_json(result))
    return 0 if result.succeeded else 1


async def _run_with_db(
    args: argparse.Namespace,
    settings: Settings,
    notice: NoticeInput,
    fetcher: WebFetcher | None,
    make_agent: AgentFactory,
) -> ExtractionResult:
    """학과 목록을 DB에서 읽고, 실행 로그를 agent_runs에 남긴다(trigger=eval)."""
    import psycopg
    from psycopg.rows import dict_row

    from app.agent_log import agent_run
    from app.extraction.store import load_departments

    async with await psycopg.AsyncConnection.connect(
        settings.database_url, row_factory=dict_row, autocommit=True, prepare_threshold=None
    ) as conn:
        departments = await load_departments(conn)
        agent = make_agent(settings, departments=departments, fetch_page=fetcher, model=args.model)
        async with agent_run(conn, trigger="eval", scenario_code=args.scenario) as logged_run:
            print(
                f"모델 {agent.model} · 학과 {len(departments)}개 · agent_runs.id = {logged_run.id}"
            )
            return await agent.run(notice, logged_run)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
