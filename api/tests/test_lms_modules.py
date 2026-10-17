"""Canvas 모듈(주차)·항목 읽기(F-52). DB·네트워크 없이 돈다.

녹화(모듈 84개·항목 87건)에서 확정한 규칙만 본다: 같은 항목은 `canvas_item_id`로만 가린다,
바로가기는 `html_url`, 빈 모듈은 오류가 아니다.
"""

from typing import Any

from app.lms.modules import NO_NAME, NO_TITLE, item, module_items, needs_items
from tests.lms_samples import DB_MODULES, ML_MODULES, MODULE_WITHOUT_ITEMS


def test_it_reads_the_items_of_every_module() -> None:
    items = module_items(DB_MODULES)
    assert [(one.canvas_item_id, one.module_name, one.title, one.item_type) for one in items] == [
        (8569302, "3주차", "3주차 강의", "ExternalTool"),
        (8569303, "3주차", "3주차 강의", "ExternalTool"),  # 제목이 같아도 둘 다 남는다
        (8569304, "3주차", "3주차 퀴즈", "Quiz"),
    ]
    assert items[0].html_url == "https://lms.test/courses/214023/modules/items/8569302"


def test_two_items_with_the_same_title_are_different_items() -> None:
    """녹화 87건 중 15쌍이 한 모듈 안에서 제목이 같았다. 제목으로 가리면 하나가 사라진다."""
    items = module_items(DB_MODULES)
    same = [one for one in items if one.title == "3주차 강의"]
    assert len(same) == 2
    assert {one.canvas_item_id for one in same} == {8569302, 8569303}


def test_an_empty_module_is_fine() -> None:
    """녹화 84개 모듈 중 47개가 `items: []`였다."""
    empty = [one for one in DB_MODULES if one["name"].startswith("4주차")]
    assert module_items(empty) == []


def test_the_module_name_is_kept_as_it_comes() -> None:
    """`1주차`·`5주차 (개천절 대체휴일)`·`Week 3 : …`가 섞인다. 주차 번호를 뽑지 않는다."""
    assert module_items(ML_MODULES)[0].module_name == "Week 3 : Trees"
    weird = [{"name": "  ", "items": [{"id": 1, "title": "가", "type": "Page"}]}]
    assert module_items(weird)[0].module_name == NO_NAME


def test_items_that_come_separately_are_merged() -> None:
    """`include[]=items`로 항목이 오지 않은 모듈은 따로 받아 합친다."""
    assert needs_items(MODULE_WITHOUT_ITEMS) == 2871999
    assert needs_items(DB_MODULES[0]) is None  # 빈 목록이어도 함께 온 것이다
    assert needs_items(DB_MODULES[1]) is None
    assert needs_items({"name": "번호 없음"}) is None

    extra = {2871999: [{"id": 999, "title": "5주차 강의", "type": "ExternalTool"}]}
    items = module_items([MODULE_WITHOUT_ITEMS], extra=extra)
    assert [(one.canvas_item_id, one.module_name) for one in items] == [(999, "5주차")]
    # 따로 받아 오지 못했으면 그 모듈은 비어 있는 것으로 둔다
    assert module_items([MODULE_WITHOUT_ITEMS]) == []


def test_it_skips_items_without_a_usable_number() -> None:
    assert item({"title": "번호 없음"}, module_name="1주차") is None
    assert item({"id": True, "title": "참"}, module_name="1주차") is None
    assert item({"id": 2**63, "title": "큰 수"}, module_name="1주차") is None
    assert item("항목이 아니다", module_name="1주차") is None
    assert module_items(["모듈이 아니다", None]) == []


def test_missing_fields_are_left_empty() -> None:
    one = item({"id": 7, "title": "  "}, module_name="1주차")
    assert one is not None
    assert one.title == NO_TITLE
    assert one.item_type is None  # 종류를 모르면 비워 둔다
    assert one.html_url is None

    numbered: dict[str, Any] = {"id": 8, "title": "가", "type": 3, "html_url": 5}
    other = item(numbered, module_name="1주차")
    assert other is not None
    assert (other.item_type, other.html_url) == (None, None)
