"""온통청년 청년정책을 받아 공고로 넣는다(PRD F-11). api 폴더에서 실행한다.

    uv run python -m app.youth.cli fetch --dry-run   # DB 없이: 받아서 몇 건이 들어갈지, 요건이 어떻게 되는지 본다
    uv run python -m app.youth.cli fetch             # DB에 넣는다. 새 정책·바뀐 정책만 요건을 다시 만든다
    uv run python -m app.youth.cli refine --sample 15 --md refine.md   # DB 없이: 서술형 자격 요건화(F-11b)를 견준다

YOUTH_API_KEY가 필요하고, fetch(--dry-run이 아닐 때)는 DATABASE_URL도 필요하다(api/.env). fetch는 서술형 자격 요건화
(YOUTH_TEXT_ENABLED)를 켰을 때만 모델을 부른다. refine은 켜지 않아도 모델을 부른다(GOOGLE_CLOUD_PROJECT) —
서술형 글이 있는 정책 몇 건을 모델로 옮겨 보고, 옮기기 전(기타 조건)과 뒤의 요건을 나란히 적는다. DB에는 쓰지 않는다.
"""

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, datetime

import psycopg

from app.agent_log import using
from app.config import Settings
from app.crawl.cli import _connect
from app.eligibility import KST, Requirement, condition_text, label
from app.extraction.models import RequirementDraft
from app.llm import LlmClient
from app.llm.gemini import GeminiClient
from app.pricing import cost_usd
from app.runtime import event_loop_factory, utf8_output
from app.youth.client import FetchResult, YouthApiError, YouthPolicyClient
from app.youth.convert import PolicyRecord, Skip, convert
from app.youth.importer import collect
from app.youth.refine import extract, merge, wanted, youth_refiner
from app.youth.regions import region_table

ClientFactory = Callable[[str], YouthPolicyClient]
LlmFactory = Callable[[Settings], LlmClient]
_SAVED = {"new": "새 공고", "updated": "바뀐 공고", "unchanged": "그대로"}
EXAMPLES = 3


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.youth.cli", description="온통청년 청년정책을 받아 공고로 넣는다"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="정책을 받아 가져올 정책을 공고로 넣는다")
    fetch.add_argument("--dry-run", action="store_true", help="DB에 넣지 않고 결과만 보여 준다")
    fetch.add_argument("--scenario", help="agent_runs.scenario_code(시나리오 실행 때, 예: S06)")
    fetch.add_argument(
        "--hide-gone",
        action="store_true",
        help="목록에서 한 번에 많이 사라진 정책도 숨긴다(온통청년에서 정말 내려갔는지 확인한 뒤)",
    )
    refine = commands.add_parser(
        "refine",
        help="서술형 자격(추가 자격·참여 제한)을 모델로 요건으로 옮겨 견준다(DB에 쓰지 않음)",
    )
    refine.add_argument(
        "--sample", type=int, default=15, help="견줄 정책 수(서술형 글이 있는 정책)"
    )
    refine.add_argument(
        "--policy", action="append", default=[], help="이 정책 번호만(여러 번 줄 수 있다)"
    )
    refine.add_argument("--model", help="모델(기본: YOUTH_TEXT_MODEL)")
    refine.add_argument("--md", help="결과를 Markdown으로 적을 파일")
    args = parser.parse_args(argv)
    if args.command == "refine" and args.sample < 1:
        parser.error("--sample은 1 이상이어야 해요")
    return args


def _gemini(settings: Settings) -> LlmClient:
    return GeminiClient(
        project=settings.google_cloud_project, location=settings.google_cloud_location
    )


async def main(
    argv: Sequence[str],
    *,
    make_client: ClientFactory = YouthPolicyClient,
    make_llm: LlmFactory = _gemini,
    settings: Settings | None = None,
) -> int:
    args = parse_args(argv)
    settings = settings or Settings()
    if not settings.youth_api_key.strip():
        print("YOUTH_API_KEY가 없어요. api/.env에 온통청년 OPEN API 인증키를 넣어 주세요")
        return 1
    today = datetime.now(KST).date()
    if args.command == "refine":
        return await refine(args, settings, make_client(settings.youth_api_key), make_llm, today)
    if args.dry_run:
        return await dry_run(make_client(settings.youth_api_key), today)
    if not settings.database_url:
        print("DATABASE_URL이 없어요(api/.env)")
        return 1
    try:
        conn, log_conn = (
            await _connect(settings.database_url),
            await _connect(settings.database_url),
        )
    except psycopg.OperationalError as exc:
        print(f"DB에 연결하지 못했어요: {exc}")
        return 1
    client = make_client(settings.youth_api_key)
    print("온통청년에서 정책을 받아 공고로 넣는 중이에요. 처음 넣을 때는 1~3분 걸려요", flush=True)
    try:
        result = await collect(
            conn,
            using(log_conn),
            client,
            today=today,
            scenario=args.scenario,
            hide_gone=args.hide_gone,
            refiner=youth_refiner(settings, make_llm(settings))
            if settings.youth_text_enabled
            else None,
        )
    except YouthApiError as exc:
        print(str(exc))
        return 1
    except psycopg.Error as exc:
        # 정책마다 트랜잭션이라 앞에서 넣은 정책은 남는다. 다시 돌리면 같은 정책은 건너뛰고 이어서 넣는다
        first = (str(exc).splitlines() or [""])[0][:200]
        print(f"DB에 넣다가 멈췄어요({type(exc).__name__}: {first}). 넣은 정책은 남아 있어요")
        return 1
    finally:
        await client.aclose()
        await conn.close()
        await log_conn.close()
    _print_fetch(result.fetch, saving=True)
    saved = sum(result.counts[key] for key in _SAVED)
    print(
        f"가져올 정책 {saved}건: "
        + " · ".join(f"{name} {result.counts[key]}" for key, name in _SAVED.items())
    )
    skipped = sum(result.skips.values())
    print(
        f"가져오지 않은 정책 {skipped}건: {_reasons(result.skips)}"
        f" → 이미 넣은 공고 중 만료 {result.counts['expired']} · 숨김 {result.counts['hidden']}"
    )
    if result.gone_kept:
        print(
            f"목록에서 한 번에 {result.gone_kept}건이 사라져 숨기지 않았어요. 온통청년 목록이 덜 왔을 수"
            " 있어요. 온통청년에서 정말 내려간 정책이면 --hide-gone을 붙여 다시 돌려 주세요"
        )
    print(f"실행 기록: agent_runs {result.run_id}")
    return 1 if result.fetch.stopped else 0


async def dry_run(client: YouthPolicyClient, today: date) -> int:
    try:
        fetched = await client.fetch_all()
    except YouthApiError as exc:
        print(str(exc))
        return 1
    finally:
        await client.aclose()
    _print_fetch(fetched, saving=False)
    table = region_table()
    records: list[PolicyRecord] = []
    skips: Counter[str] = Counter()
    for policy in fetched.policies:
        converted = convert(policy, today, table)
        if isinstance(converted, Skip):
            skips[converted.reason] += 1
        else:
            records.append(converted)
    print(f"가져올 정책 {len(records)}건 · 가져오지 않음 {_reasons(skips)}")
    fields = Counter(
        label(_requirement(draft)) for record in records for draft in record.requirements
    )
    empty = sum(1 for record in records if not record.requirements)
    review = sum(1 for r in records if any(d.field == "other" for d in r.requirements))
    print(
        f"조건 없는 정책 {empty}건 · 기타 조건(원문 확인)이 있는 정책 {review}건 · 항목별 조건 수 "
        + " · ".join(f"{name} {count}" for name, count in fields.most_common())
    )
    print("DB에는 넣지 않았어요(--dry-run). 예시:")
    examples = [record for record in records if record.requirements][:EXAMPLES]
    for record in examples or records[:EXAMPLES]:
        deadline = record.deadline_at.strftime("%Y-%m-%d") if record.deadline_at else "없음"
        print(f"  {record.title} · {record.organizer or '-'} · 마감 {deadline}")
        for draft in record.requirements:
            requirement = _requirement(draft)
            text = condition_text(requirement)
            print(f"    {draft.clause_no}. {label(requirement)} {text[:120]}")
        if record.review_reasons:
            print(f"    원문 확인 필요: {', '.join(record.review_reasons)}")
    return 1 if fetched.stopped else 0


async def refine(
    args: argparse.Namespace,
    settings: Settings,
    client: YouthPolicyClient,
    make_llm: LlmFactory,
    today: date,
) -> int:
    """서술형 글이 있는 정책 몇 건을 모델로 옮겨 보고, 옮기기 전과 뒤의 요건을 나란히 적는다(DB에 쓰지 않는다)."""
    try:
        fetched = await client.fetch_all()
    except YouthApiError as exc:
        print(str(exc))
        return 1
    finally:
        await client.aclose()
    table = region_table()
    picked: list[tuple[PolicyRecord, dict[str, str]]] = []
    for policy in fetched.policies:
        if args.policy and str(policy.get("plcyNo")) not in args.policy:
            continue
        converted = convert(policy, today, table)
        texts = wanted(policy)
        if not isinstance(converted, Skip) and texts:
            picked.append((converted, texts))
    picked = picked[: len(args.policy) or args.sample]
    if not picked:
        print("가져올 정책 중 서술형 자격 글이 있는 정책이 없어요")
        return 1
    model = args.model or settings.youth_text_model
    llm = make_llm(settings)
    lines = [f"# 청년정책 서술형 자격 요건화 견주기 ({today.isoformat()}, {model})", ""]
    covered = conditions = dropped = tokens_in = tokens_out = failed = 0
    for record, texts in picked:
        lines += [f"## {record.title} ({record.external_id})", ""]
        lines += [f"- **{name}**: {text}" for name, text in texts.items()]
        try:
            found = await extract(llm, model=model, texts=texts)
        except Exception as exc:  # 한 건이 실패해도 견주기는 이어 간다
            failed += 1
            lines += ["", f"모델이 답하지 않았어요: {type(exc).__name__}", ""]
            continue
        if found.reply is not None:
            tokens_in += found.reply.usage.input_tokens
            tokens_out += found.reply.usage.output_tokens
        after = merge(record, found, texts)
        covered += len(found.covered)
        conditions += len(found.conditions)
        dropped += found.dropped
        lines += ["", "| 전(코드 변환) | 뒤(요건화) |", "| --- | --- |"]
        before_rows = [_row(draft) for draft in record.requirements]
        after_rows = [_row(draft) for draft in after.requirements]
        for index in range(max(len(before_rows), len(after_rows))):
            left = before_rows[index] if index < len(before_rows) else ""
            right = after_rows[index] if index < len(after_rows) else ""
            lines.append(f"| {left} | {right} |")
        lines += [
            "",
            f"옮긴 조건 {len(found.conditions)} · 버린 조건 {found.dropped} · 기타 조건을 뺀 글: "
            + (", ".join(found.covered) or "없음"),
            "",
        ]
    cost = cost_usd(llm.provider, model, tokens_in, tokens_out, today)
    summary = (
        f"정책 {len(picked)}건 · 옮긴 조건 {conditions} · 버린 조건 {dropped} · 기타 조건을 뺀 글 {covered}"
        f" · 실패 {failed} · 토큰 {tokens_in:,}/{tokens_out:,} · 비용 ${float(cost):.4f}"
    )
    lines.insert(2, summary + "\n")
    text = "\n".join(lines) + "\n"
    if args.md:
        with open(args.md, "w", encoding="utf-8") as out:
            out.write(text)
        print(f"{summary}\n결과: {args.md}")
    else:
        print(text)
    return 1 if failed else 0


def _row(draft: RequirementDraft) -> str:
    requirement = _requirement(draft)
    text = condition_text(requirement)[:80].replace("|", "/")
    return f"{draft.clause_no}. {label(requirement)} {text}"


def _requirement(draft: RequirementDraft) -> Requirement:
    return Requirement(
        id="-",
        clause_no=draft.clause_no,
        field=draft.field,
        operator=draft.operator,
        value=draft.value,
        basis=draft.basis,
        is_ambiguous=draft.is_ambiguous,
        evidence_text=draft.evidence_text,
    )


def _print_fetch(fetched: FetchResult, *, saving: bool) -> None:
    print(
        f"온통청년 정책 {len(fetched.policies)}건 받음"
        f"(전체 {fetched.total}건, 호출 {fetched.calls}회, {round(fetched.seconds)}초)"
    )
    if fetched.skipped:
        print(f"읽지 못해 건너뛴 정책 {len(fetched.skipped)}건(순번 {list(fetched.skipped[:10])})")
    if fetched.stopped:
        then = (
            "받은 정책은 넣었어요. 몇 분 뒤 다시 돌리면 나머지를 넣어요"
            if saving
            else "몇 분 뒤 다시 돌려 주세요"
        )
        print(f"끝까지 받지 못했어요: {fetched.stopped}. {then}")
    if saving and not fetched.complete:
        print("목록을 빠짐없이 받지 못해 목록에서 사라진 정책은 숨기지 않았어요")


def _reasons(skips: Counter[str]) -> str:
    return " · ".join(f"{reason} {count}" for reason, count in skips.most_common()) or "없음"


if __name__ == "__main__":
    utf8_output()  # 출력을 파이프로 보낼 때 cp949에 없는 글자에서 멈추지 않게(Windows)
    sys.exit(asyncio.run(main(sys.argv[1:]), loop_factory=event_loop_factory()))
