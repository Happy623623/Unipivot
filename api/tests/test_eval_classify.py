"""공지 분류 평가 세트 EV-CLASSIFY의 셈과 명령(app/eval/classify.py, O3).

실제 정답셋(과목 공지 20건)은 교수가 쓴 글이라 레포에 없다. 여기서는 우리가 쓴 공지 여섯 건과 녹화한 답으로
셈(혼동행렬·기회성 재현율·바뀐 날 일치율·제출 없음)과 합격선, 녹화·재생, 정답 틀을 본다.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.eval.classify import (
    SET,
    Item,
    load_set,
    main,
    replies_of,
    run_set,
    score,
    template,
)
from app.eval.fakes import RecordedLlm, tool_reply
from app.lms.classify import SUBMIT

pytestmark = pytest.mark.anyio
POSTED = date(2026, 10, 1)
TODAY = date(2026, 11, 26)


def item(id: str, category: str, change_date: str | None = None) -> dict[str, Any]:
    return {
        "id": id,
        "title": f"{id} 공지 제목",
        "body": f"{id} 공지 본문입니다.",
        "posted_on": POSTED.isoformat(),
        "expected": {"category": category, "change_date": change_date},
    }


# 정답 여섯 건: 일정 변경 둘(바뀐 날 있음), 기회성 둘, 자료 하나, 그 밖 하나
ITEMS = [
    item("n1", "schedule_change", "2026-10-08"),
    item("n2", "schedule_change", "2026-10-15"),
    item("n3", "opportunity"),
    item("n4", "opportunity"),
    item("n5", "material"),
    item("n6", "general"),
]
# 엔진 답: n2는 날짜가 하루 틀리고, n4는 기회성을 놓치고, n6은 제출하지 않았다(general로 둔다)
MISSES = {
    "n1": {"category": "schedule_change", "change_date": "2026-10-08", "change_kind": "cancel"},
    "n2": {"category": "schedule_change", "change_date": "2026-10-16", "change_kind": "makeup"},
    "n3": {"category": "opportunity", "opportunity_category": "research"},
    "n4": {"category": "general"},
    "n5": {"category": "material"},
    "n6": None,
}


def answers_file(tmp_path: Path, items: list[dict[str, Any]] = ITEMS) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(json.dumps({"set": SET, "items": items}, ensure_ascii=False), encoding="utf-8")
    return path


def replay_file(tmp_path: Path, replies: dict[str, Any], model: str = "rec-model") -> Path:
    path = tmp_path / "replies.json"
    path.write_text(json.dumps({"set": SET, "model": model, "replies": replies}), encoding="utf-8")
    return path


def recorded(replies: dict[str, Any]) -> RecordedLlm:
    return RecordedLlm(
        *(
            tool_reply(SUBMIT, summary="한 줄 요약", **reply) if reply else "고르지 못했어요."
            for reply in replies.values()
        )
    )


async def test_the_score_counts_the_matrix_recall_dates_and_missing_submissions(
    tmp_path: Path,
) -> None:
    items = load_set(answers_file(tmp_path))
    llm = recorded(MISSES)
    outcomes = await run_set(llm, "rec-model", items, priced_on=None)
    found = score(outcomes)

    assert [ask.force_tool for ask in llm.asks] == [SUBMIT] * 6  # 앱과 같은 분류 함수를 부른다
    assert (found.items, found.correct, found.accuracy) == (6, 5, 0.8333)
    assert found.matrix["opportunity"] == {
        "schedule_change": 0,
        "material": 0,
        "opportunity": 1,
        "general": 1,
    }
    assert (found.opportunities, found.found_opportunities, found.opportunity_recall) == (
        2,
        1,
        0.5,
    )
    assert (found.dates, found.dates_matched, found.date_match_rate) == (2, 1, 0.5)
    assert found.no_submission == 1 and found.matrix["general"]["general"] == 1
    assert found.cost_usd == 0.0  # 녹화 답은 비용을 세지 않는다
    assert found.failures == ["기회성 재현율 0.50 < 0.9"]


async def test_a_set_that_finds_every_opportunity_passes_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    perfect = {**MISSES, "n4": {"category": "opportunity"}}
    out = tmp_path / "result.json"
    code = await main(
        [
            str(answers_file(tmp_path)),
            "--replay",
            str(replay_file(tmp_path, perfect)),
            "--out",
            str(out),
        ],
        today=TODAY,
    )

    assert code == 0
    shown = capsys.readouterr().out
    assert "| **opportunity** | 0 | 0 | 2 | 0 | 2 |" in shown
    assert "| 기회성 재현율 | 1.00 (2/2) | ≥ 0.9 |" in shown
    assert "합격선: **통과**" in shown
    assert (
        "| classify.announcement | 1 | rec-model | EV-CLASSIFY | 2026-11-26 | 정확도 1.00"
        " · 기회성 재현율 1.00 · 바뀐 날 0.50 · 제출 없음 1 | 6건 |" in shown
    )
    result = json.loads(out.read_text(encoding="utf-8"))
    assert (result["engine"], result["version"], result["model"]) == (
        "classify.announcement",
        1,
        "rec-model",
    )
    assert result["score"]["failures"] == []


async def test_a_missed_opportunity_fails_the_gate_and_keeps_no_announcement_text(
    tmp_path: Path,
) -> None:
    out = tmp_path / "result.json"
    md = tmp_path / "result.md"
    code = await main(
        [
            str(answers_file(tmp_path)),
            "--replay",
            str(replay_file(tmp_path, MISSES)),
            "--out",
            str(out),
            "--md",
            str(md),
        ],
        today=TODAY,
    )

    assert code == 1  # 기회성 재현율 0.5 < 0.9
    assert "실패: 기회성 재현율 0.50 < 0.9" in md.read_text(encoding="utf-8")
    written = out.read_text(encoding="utf-8")
    assert "공지 제목" not in written and "공지 본문" not in written  # 교수가 쓴 글은 남기지 않는다
    rows = {row["id"]: row for row in json.loads(written)["items"]}
    assert (rows["n4"]["expected"], rows["n4"]["actual"]) == ("opportunity", "general")
    assert (rows["n2"]["expected_date"], rows["n2"]["actual_date"]) == ("2026-10-15", "2026-10-16")
    assert rows["n6"]["submitted"] is False


async def test_a_recorded_run_replays_to_the_same_score(tmp_path: Path) -> None:
    """--record로 남긴 답을 --replay로 다시 셈하면 같은 결과다. 녹화에는 요약(공지 글에서 나온 말)이 없다."""
    items = load_set(answers_file(tmp_path))
    first = await run_set(recorded(MISSES), "real-model", items, priced_on=None)
    record = replies_of(first, "real-model")
    assert "summary" not in json.dumps(record)
    assert record["replies"]["n6"] is None
    path = replay_file(tmp_path, record["replies"], model=record["model"])

    out = tmp_path / "again.json"
    assert await main([str(answers_file(tmp_path)), "--replay", str(path), "--out", str(out)]) == 1
    again = json.loads(out.read_text(encoding="utf-8"))
    assert again["model"] == "real-model"
    assert again["score"]["matrix"] == score(first).matrix


async def test_the_template_leaves_the_answer_blank() -> None:
    """DB에서 뽑은 공지 목록 → 정답 틀. 게시일은 KST 날짜이고, 정답 칸은 비워 둔다(엔진 답을 미리 채우지 않는다)."""
    made = template(
        [
            {
                "id": "a1",
                "title": "휴강 안내",
                "message": "10월 8일 수업은 휴강합니다.",
                "posted_at": "2026-09-30T16:00:00+00:00",
            },
            {"id": "a2", "title": "자료", "message": None, "posted_at": None},
        ]
    )
    assert made["set"] == SET
    assert made["items"][0] == {
        "id": "a1",
        "title": "휴강 안내",
        "body": "10월 8일 수업은 휴강합니다.",
        "posted_on": "2026-10-01",
        "expected": {"category": "", "change_date": None},
    }
    assert made["items"][1]["posted_on"] is None and made["items"][1]["body"] is None


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([item("x1", "")], "정답 갈래가"),  # 틀을 채우지 않고 돌렸다
        ([item("x1", "general", "2026-10-08")], "바뀐 날은 일정 변경 공지에만"),
        ([item("x1", "general"), item("x1", "material")], "번호(id)가 겹치는"),
        ([{**item("x1", "schedule_change"), "posted_on": "10월 1일"}], "YYYY-MM-DD"),
    ],
)
async def test_a_bad_answer_file_is_refused_with_what_to_fix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    items: list[dict[str, Any]],
    message: str,
) -> None:
    replies = replay_file(tmp_path, {})
    assert await main([str(answers_file(tmp_path, items)), "--replay", str(replies)]) == 2
    assert message in capsys.readouterr().err


async def test_a_replay_without_an_answer_for_every_announcement_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    partial = replay_file(tmp_path, {"n1": MISSES["n1"]})
    assert await main([str(answers_file(tmp_path)), "--replay", str(partial)]) == 2
    assert "녹화에 없는 공지가 있어요: n2" in capsys.readouterr().err


def test_items_keep_the_dates_as_dates(tmp_path: Path) -> None:
    (first, *_) = load_set(answers_file(tmp_path))
    assert first == Item(
        id="n1",
        title="n1 공지 제목",
        body="n1 공지 본문입니다.",
        posted_on=POSTED,
        category="schedule_change",
        change_date=date(2026, 10, 8),
    )
