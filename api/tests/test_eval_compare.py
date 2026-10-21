"""모델 비교 실험 CLI(app/eval/compare.py): 셈 함수와 흐름(가짜 LLM). DB 시험은 DATABASE_URL이 있을 때만."""

import json
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from app.config import Settings
from app.eligibility import Profile
from app.eval import compare
from app.eval.compare_metrics import Confusion, Match, condition_key, conditions, judge, percentile
from app.extraction import ExtractionAgent
from app.extraction.models import NoticeInput
from app.extraction.prompt import SUBMIT
from app.posters.prompt import SUBMIT as POSTER_SUBMIT
from tests import hanyang_pages, samples
from tests.hanyang_pages import save_notice
from tests.llm_fakes import ScriptedLlm, call
from tests.test_posters_extract import args as poster_args

pytestmark = pytest.mark.anyio

GPA = {"clause_no": 1, "field": "gpa_last_semester", "operator": "gte", "value": 3.0, "basis": None}
GRADE = {"clause_no": 2, "field": "grade", "operator": "in", "value": [2, 3], "basis": None}


def test_conditions_ignore_clause_numbers_and_key_order() -> None:
    renumbered = {**GRADE, "clause_no": 7, "value": [2, 3]}
    assert condition_key(GRADE) == condition_key(renumbered)
    assert condition_key({**GPA, "value": 3.5}) != condition_key(GPA)
    match = Match()
    match.add(conditions([GPA]), conditions([GPA, GRADE]))
    assert (match.precision, match.recall, match.jaccard) == (1.0, 0.5, 0.5)
    assert match.f1 == pytest.approx(2 / 3)
    assert Match().f1 is None


def test_judgments_use_the_app_engine_and_count_missed_eligibility() -> None:
    student = Profile(grade=3, gpa_last_semester=3.0)
    basis = date(2026, 10, 21)
    assert judge([GPA, GRADE], student, basis=basis, departments=[]) == "eligible"
    stricter = [{**GPA, "value": 3.5}]
    assert judge(stricter, student, basis=basis, departments=[]) == "ineligible"
    # 요건을 못 읽은 결과는 앱처럼 지원 가능으로 내보내지 않는다
    assert judge([], student, basis=basis, departments=[], known=False) != "eligible"
    assert judge([{**GPA, "value": "모양이 틀림"}], student, basis=basis, departments=[]) == (
        "undetermined"
    )
    confusion = Confusion()
    for pair in [("eligible", "ineligible"), ("eligible", "eligible"), ("ineligible", "eligible")]:
        confusion.add(*pair)
    assert (confusion.total, confusion.agree) == (3, 1)
    assert (confusion.eligible_to_ineligible, confusion.ineligible_to_eligible) == (1, 1)
    assert confusion.table()[0] == [1, 0, 1]


def test_an_engine_error_counts_as_undetermined(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("값 모양이 틀림")

    monkeypatch.setattr("app.eval.compare_metrics.check_eligibility", broken)
    student = Profile(grade=3, gpa_last_semester=3.0)
    assert judge([GPA], student, basis=date(2026, 10, 21), departments=[]) == "undetermined"


def outcome(model: str, item: str, **values: Any) -> compare.Outcome:
    values.setdefault("kind", "notice")
    values.setdefault("attempt", 1)
    values.setdefault("ok", True)
    values.setdefault("wall_ms", 1000)
    return compare.Outcome(item=item, model=model, **values)


def test_the_summary_skips_failed_references_and_repeats() -> None:
    """기준 모델이 실패한 항목은 견주지 않고, 비교 모델이 실패하면 판정하지 못함으로 세고,
    반복 실행(2번째부터)은 정확도에 넣지 않는다. 포스터 제목은 빈칸을 무시하고 견준다."""
    base, lite = "gemini-3.8-flash", "gemini-3.5-flash-lite"
    notice = {"requirements": [GPA], "deadline": "2026-10-24", "basis": "2026-10-21"}
    outcomes = [
        outcome(base, "A", ok=False),
        outcome(lite, "A", **notice),
        outcome(base, "B", **notice),
        outcome(lite, "B", ok=False),
        outcome(lite, "B", attempt=2, **notice),
        outcome(base, "p.jpg", kind="poster", title="AI 공모전", deadline="2026-10-20"),
        outcome(lite, "p.jpg", kind="poster", title=" AI  공모전", deadline="2026-10-20"),
    ]
    profiles = [("평점 3.0", Profile(gpa_last_semester=3.0))]
    row = compare.summarize(outcomes, [base, lite], None, profiles, [], today=date(2026, 10, 21))[
        "models"
    ][lite]
    assert (row["notices"], row["judgments"], row["judgment_agree"]) == (2, 1, 0.0)
    assert row["confusion"][0] == [0, 1, 0]  # 기준은 적격, 실패한 비교 모델은 판정하지 못함
    assert row["deadline_match"] == 0.0
    assert row["poster_title_match"] == 1.0
    assert row["runs"] == 4 and row["succeeded"] == 3


TODAY = date(2026, 10, 21)
BASE, LITE = "gemini-3.8-flash", "gemini-3.5-flash-lite"


def lite_row(outcomes: list[compare.Outcome], profiles: list[tuple[str, Profile]]) -> Any:
    return compare.summarize(outcomes, [BASE, LITE], None, profiles, [], today=TODAY)["models"][
        LITE
    ]


def test_an_unreadable_reference_is_not_counted_as_eligible() -> None:
    """기준 모델도 앱처럼 판정한다: 요건 0개 + 원문 확인이면 못 읽은 것(지원 가능이 아니다)."""
    unread = {"requirements": [], "needs_review": True, "basis": "2026-10-21"}
    profiles = [("아무나", Profile())]
    row = lite_row([outcome(BASE, "A", **unread), outcome(LITE, "A", **unread)], profiles)
    assert (row["judgment_agree"], row["eligible_to_ineligible"]) == (1.0, 0)
    # 기준이 못 읽고 비교 모델이 평점 요건을 찾았으면 "적격 → 부적격"이 아니다
    found = {"requirements": [GPA], "basis": "2026-10-21"}
    row = lite_row(
        [outcome(BASE, "A", **unread), outcome(LITE, "A", **found)],
        [("평점 2.0", Profile(gpa_last_semester=2.0))],
    )
    assert row["eligible_to_ineligible"] == 0


def test_each_side_is_judged_on_its_own_basis_date() -> None:
    """만 34세 이하 요건: 기준은 10/21에 34세(적격), 비교 모델이 기준일을 이듬해로 읽으면 35세(부적격)."""
    age = {"clause_no": 1, "field": "age", "operator": "lte", "value": 34, "basis": None}
    profiles = [("1992-01-01생", Profile(birth_date=date(1992, 1, 1)))]
    row = lite_row(
        [
            outcome(BASE, "A", requirements=[age], basis="2026-10-21"),
            outcome(LITE, "A", requirements=[age], basis="2027-03-01"),
        ],
        profiles,
    )
    assert row["eligible_to_ineligible"] == 1 and row["f1"] == 1.0


def test_cost_and_latency_are_per_run_and_split_by_kind() -> None:
    runs = [
        outcome(LITE, "A", attempt=n, cost_usd=0.01, wall_ms=ms, ok=n != 2)
        for n, ms in ((1, 1000), (2, 3000), (3, 2000))
    ]
    runs.append(outcome(LITE, "p", kind="poster", cost_usd=0.002, wall_ms=9000, ok=False))
    row = lite_row(runs, [])
    assert (row["cost_per_notice_usd"], row["cost_per_poster_usd"]) == (0.01, 0.002)
    assert (row["notice_p50_ms"], row["notice_p95_ms"]) == (2000, 3000)
    assert row["poster_p95_ms"] == 9000  # 실패한 실행(공지 2번째·포스터)도 응답시간에 넣는다


def test_conditions_with_the_same_meaning_match() -> None:
    assert condition_key({**GRADE, "value": [3, 2]}) == condition_key(GRADE)
    assert condition_key({**GPA, "value": 3}) == condition_key({**GPA, "value": 3.0})
    nothing = Match()
    nothing.add(set(), conditions([GPA]))  # 조건을 하나도 못 낸 모델은 F1 0이다
    assert (nothing.precision, nothing.f1) == (None, 0.0)


async def test_a_notice_without_any_date_is_judged_today() -> None:
    class NoDates:
        model = BASE

        async def run(self, notice: Any, log: Any) -> Any:
            return SimpleNamespace(
                deadline_at=None,
                eligibility_basis_date=None,
                succeeded=False,
                needs_review=True,
                requirements=[],
            )

    result = await compare.run_notice(
        NoDates(),  # type: ignore[arg-type]
        NoticeInput(title="t", body="x"),
        compare.Collector(),
        item="A",
        attempt=1,
        today=TODAY,
    )
    assert (result.ok, result.basis) == (False, "2026-10-21")


async def test_a_bad_answers_file_stops_before_any_model_call(tmp_path: Path) -> None:
    folder = notice_folder(tmp_path / "공지")
    made: list[str] = []

    def make_agent(settings: Settings, **options: Any) -> ExtractionAgent:
        made.append(options["model"])
        raise AssertionError("모델을 부르면 안 된다")

    for bad in ({"notices": []}, {"notices": {"1 장학": {"deadline": None}}}, ["x"]):
        answers = tmp_path / "answers.json"
        answers.write_text(json.dumps(bad), encoding="utf-8")
        argv = [str(folder), "--answers", str(answers), "--out", str(tmp_path / "o.json")]
        with pytest.raises(SystemExit):
            await compare.main(argv, make_agent=make_agent, settings=Settings())
    assert made == []


async def test_outcomes_are_written_before_the_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """셈이 실패해도 돈 들인 실행 결과는 파일에 남는다."""

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("셈 실패")

    monkeypatch.setattr(compare, "summarize", broken)
    replies = {"gemini-3.8-flash": [submit(3.0)]}
    posters = {"gemini-3.8-flash": [call(POSTER_SUBMIT, **poster_args())]}
    with pytest.raises(ValueError):
        await run_compare(tmp_path, ["--models", "gemini-3.8-flash"], replies, posters)
    saved = json.loads((tmp_path / "compare.json").read_text(encoding="utf-8"))
    assert [o["kind"] for o in saved["outcomes"]] == ["notice", "poster"]


def test_bad_arguments_stop_early(tmp_path: Path) -> None:
    for extra in (["--repeat", "0"], ["--models", "gemini-9-pro"]):
        with pytest.raises(SystemExit):
            compare.parse_args([str(tmp_path), *extra])


async def test_folders_with_the_same_name_are_refused(tmp_path: Path) -> None:
    one = notice_folder(tmp_path / "가")
    two = notice_folder(tmp_path / "나")
    assert one.name == two.name
    with pytest.raises(SystemExit):
        await compare.main(
            [str(one), str(two), "--out", str(tmp_path / "o.json")], settings=Settings()
        )


def test_percentile_is_nearest_rank() -> None:
    assert percentile([], 0.5) is None
    assert percentile([300, 100, 200], 0.5) == 200
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10


def submit(value: float) -> Any:
    return call(
        SUBMIT,
        requirements=[
            {
                "clause_no": 1,
                "field": "gpa_last_semester",
                "operator": "gte",
                "value_json": json.dumps(value),
                "evidence_text": "직전 학기 평점평균 3.0 이상",
                "is_ambiguous": False,
            }
        ],
        documents=[],
        deadline="2026-10-24",
        confidence=0.9,
        needs_review=False,
    )


def notice_folder(root: Path) -> Path:
    body = "<p>직전 학기 평점평균 3.0 이상인 학생</p>"
    return save_notice(root / "1 장학", hanyang_pages.detail(files=(), body=body), {})


async def run_compare(
    tmp_path: Path, extra: list[str], replies: dict[str, list[Any]], posters: dict[str, list[Any]]
) -> tuple[int, dict[str, Any], str]:
    folder = notice_folder(tmp_path / "공지")
    poster_dir = tmp_path / "포스터"
    poster_dir.mkdir()
    (poster_dir / "a.jpg").write_bytes(samples.JPEG)
    (poster_dir / "메모.txt").write_text("포스터 아님")
    made: list[tuple[str, str]] = []
    llms = {model: ScriptedLlm(*answers) for model, answers in replies.items()}
    poster_llm = ScriptedLlm(*[reply for model in posters for reply in posters[model]])

    def make_agent(settings: Settings, **options: Any) -> ExtractionAgent:
        made.append((options["model"], settings.vision_model))
        return ExtractionAgent(llms[options["model"]], model=options["model"])

    out = tmp_path / "compare.json"
    argv = [str(folder), "--posters", str(poster_dir), "--out", str(out), "--today", "2026-10-15"]
    argv += extra
    code = await compare.main(
        argv, make_agent=make_agent, make_llm=lambda _s: poster_llm, settings=Settings()
    )
    assert made == [(m, m) for m in replies]  # 글·첨부 이미지 모두 그 모델로
    return code, json.loads(out.read_text(encoding="utf-8")), poster_llm


async def test_two_models_are_compared_against_the_first_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    replies = {"gemini-3.8-flash": [submit(3.0)], "gemini-3.5-flash-lite": [submit(3.5)]}
    posters = {
        "gemini-3.8-flash": [call(POSTER_SUBMIT, **poster_args())],
        "gemini-3.5-flash-lite": [call(POSTER_SUBMIT, **poster_args(deadline="2026-10-21T18:00"))],
    }
    template = tmp_path / "answers.json"
    code, data, poster_llm = await run_compare(
        tmp_path, ["--template", str(template)], replies, posters
    )
    assert code == 0
    outcomes = data["outcomes"]
    # 항목마다 모델을 번갈아 돈다
    assert [(o["kind"], o["model"]) for o in outcomes] == [
        ("notice", "gemini-3.8-flash"),
        ("notice", "gemini-3.5-flash-lite"),
        ("poster", "gemini-3.8-flash"),
        ("poster", "gemini-3.5-flash-lite"),
    ]
    # 비교에 쓰는 칸만 남는다(포스터의 근거 문장 같은 원문은 없다)
    assert all(
        list(r) == list(compare.REQUIREMENT_KEYS) for o in outcomes for r in o["requirements"]
    )
    assert data["priced_on"] and data["today"] == "2026-10-15"
    assert [r.model for r in poster_llm.requests] == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    first = outcomes[0]
    assert first["deadline"] == "2026-10-24" and first["submits"] == 1
    assert first["requirements"][0]["value"] == 3.0
    assert first["input_tokens"] == 1000 and first["cost_usd"] > 0
    assert "본문" not in json.dumps(outcomes, ensure_ascii=False)  # 공고 글은 남기지 않는다
    summary = data["summary"]
    assert summary["reference"] == "model:gemini-3.8-flash"
    lite = summary["models"]["gemini-3.5-flash-lite"]
    assert (lite["jaccard"], lite["deadline_match"]) == (0.0, 1.0)
    # 평점 3.0인 가상 프로필(학부 3학년)은 3.8 Flash로는 적격, Flash-Lite(3.5 이상)로는 부적격이다
    assert lite["eligible_to_ineligible"] >= 1
    assert (lite["poster_title_match"], lite["poster_deadline_match"]) == (1.0, 0.0)
    base = summary["models"]["gemini-3.8-flash"]
    assert base["judgments"] == 0 and base["f1"] is None  # 기준 모델은 자기와 견주지 않는다
    table = capsys.readouterr().out
    assert "| gemini-3.5-flash-lite | 2 | 2 |" in table
    written = json.loads(template.read_text(encoding="utf-8"))
    assert written["notices"]["1 장학"]["requirements"] == [
        {
            "clause_no": 1,
            "field": "gpa_last_semester",
            "operator": "gte",
            "value": 3.0,
            "basis": None,
            "is_ambiguous": False,
        }
    ]
    assert written["posters"]["a.jpg"]["deadline"] == "2026-10-20"


async def test_answers_are_the_reference_when_given(tmp_path: Path) -> None:
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "notices": {"1 장학": {"deadline": "2026-10-24", "requirements": [GPA]}},
                "posters": {"a.jpg": {"title": "다른 제목", "deadline": "2026-10-20"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps([{"name": "평점 3.2", "gpa_last_semester": 3.2}], ensure_ascii=False),
        encoding="utf-8",
    )
    md = tmp_path / "compare.md"
    replies = {"gemini-3.8-flash": [submit(3.0)]}
    posters = {"gemini-3.8-flash": [call(POSTER_SUBMIT, **poster_args())]}
    code, data, _ = await run_compare(
        tmp_path,
        [
            "--answers",
            str(answers),
            "--profiles",
            str(profiles),
            "--models",
            "gemini-3.8-flash",
            "--md",
            str(md),
        ],
        replies,
        posters,
    )
    row = data["summary"]["models"]["gemini-3.8-flash"]
    assert code == 0 and data["summary"]["reference"] == "answers"
    assert (row["f1"], row["deadline_match"], row["judgments"], row["judgment_agree"]) == (
        1.0,
        1.0,
        1,
        1.0,
    )
    assert (row["poster_title_match"], row["poster_deadline_match"]) == (0.0, 1.0)
    assert md.read_text(encoding="utf-8").startswith("기준: 정답")


async def test_a_failed_run_is_kept_and_the_exit_code_says_so(tmp_path: Path) -> None:
    replies = {"gemini-3.8-flash": []}  # 모델이 답하지 않는다(가짜가 AssertionError)
    posters = {"gemini-3.8-flash": ["글만 답함"]}
    code, data, _ = await run_compare(tmp_path, ["--models", "gemini-3.8-flash"], replies, posters)
    assert code == 1
    assert [o["ok"] for o in data["outcomes"]] == [False, False]
    assert all(o["error"] for o in data["outcomes"])


def test_folders_or_posters_are_required() -> None:
    with pytest.raises(SystemExit):
        compare.parse_args([])


def test_the_default_profiles_parse() -> None:
    names = [name for name, _ in compare.load_profiles(None)]
    assert len(names) == 5 and len(set(names)) == 5


@pytest.mark.db
@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL이 없어서 건너뜀")
async def test_with_db_each_run_is_logged_as_an_eval_scenario(tmp_path: Path) -> None:
    """--db: 학과 목록을 DB에서 읽고 실행마다 agent_runs(trigger=eval, scenario_code=CMP-…)를 남긴다."""
    settings = Settings(database_url=os.environ["DATABASE_URL"])
    folder = notice_folder(tmp_path / "공지")
    seen: list[int] = []

    def make_agent(settings: Settings, **options: Any) -> ExtractionAgent:
        seen.append(len(options["departments"]))
        return ExtractionAgent(ScriptedLlm(submit(3.0)), model=options["model"])

    out = tmp_path / "compare.json"
    argv = [str(folder), "--db", "--models", "gemini-3.8-flash", "--out", str(out)]
    assert await compare.main(argv, make_agent=make_agent, settings=settings) == 0
    conn = await psycopg.AsyncConnection.connect(settings.database_url, row_factory=dict_row)
    try:
        run = await (
            await conn.execute(
                "select id, status::text as status from agent_runs"
                " where trigger_type = 'eval' and scenario_code = 'CMP-F38-N01'"
                " order by started_at desc limit 1"
            )
        ).fetchone()
        assert run is not None and run["status"] == "succeeded"
        calls = await (
            await conn.execute("select model from llm_calls where run_id = %s", (run["id"],))
        ).fetchall()
        assert [one["model"] for one in calls] == ["gemini-3.8-flash"]
        await conn.execute("delete from agent_runs where id = %s", (run["id"],))
        await conn.commit()
    finally:
        await conn.close()
    assert seen and seen[0] > 0  # 학과 목록(시드)을 읽었다


@pytest.mark.db
@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL이 없어서 건너뜀")
async def test_with_db_a_failed_run_is_logged_as_failed(tmp_path: Path) -> None:
    """지표가 agent_runs에서 나오므로, 요건을 못 읽은 비교 실행은 실패로 남아야 한다."""
    settings = Settings(database_url=os.environ["DATABASE_URL"])
    folder = notice_folder(tmp_path / "공지")

    def make_agent(settings: Settings, **options: Any) -> ExtractionAgent:
        return ExtractionAgent(ScriptedLlm(), model=options["model"])  # 답하지 않는다

    argv = [str(folder), "--db", "--models", "gemini-3.5-flash-lite"]
    argv += ["--out", str(tmp_path / "compare.json")]
    assert await compare.main(argv, make_agent=make_agent, settings=settings) == 1
    conn = await psycopg.AsyncConnection.connect(settings.database_url, row_factory=dict_row)
    try:
        run = await (
            await conn.execute(
                "select id, status::text as status from agent_runs"
                " where trigger_type = 'eval' and scenario_code = 'CMP-FL35-N01'"
                " order by started_at desc limit 1"
            )
        ).fetchone()
        assert run is not None and run["status"] == "failed"
        await conn.execute("delete from agent_runs where id = %s", (run["id"],))
        await conn.commit()
    finally:
        await conn.close()


async def test_the_real_supabase_db_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = notice_folder(tmp_path / "공지")
    argv = [str(folder), "--db", "--out", str(tmp_path / "x.json")]
    for url, host in (
        ("postgresql://u@db.abcd.supabase.co:5432/postgres", ""),
        ("postgresql://u@DB.ABCD.SUPABASE.CO:5432/postgres", ""),
        ("postgresql:///postgres", "db.abcd.supabase.co"),
    ):
        monkeypatch.setenv("PGHOST", host)
        with pytest.raises(SystemExit):
            await compare.main(argv, settings=Settings(database_url=url))
