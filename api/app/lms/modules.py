"""Canvas 모듈(주차)·항목 응답 → 저장할 값 (F-52, API 명세 9장의 10/16 녹화 규칙).

녹화(6과목·모듈 84개·항목 87건)에서 확정한 것만 따른다:

- 같은 항목인지는 **`canvas_item_id`로만** 가린다. 한 모듈에 제목이 같은 항목이 둘씩 있다(15쌍)
- 항목 `type`은 `ExternalTool`(LearningX 출석·영상 LTI) 75 · `Assignment` 7 · `Quiz` 4 · `Page` 1이었고
  **`File`은 한 건도 없었다**. 자료 파일은 Canvas에 없고 LearningX 안에서만 열린다(PRD 5-6)
- 바로가기는 `html_url`이다(`url`은 API 주소라 학생이 열 수 없다)
- 모듈 이름은 `1주차`·`5주차 (개천절 대체휴일)`·`Week 3 : …`가 섞인다. 그대로 저장하고 주차 번호를
  따로 뽑지 않는다. `position`은 연속이 아니라(1주차가 position 17인 과목이 있다) 저장하지 않는다
- 항목이 없는 모듈이 흔하다(84개 중 47개가 `items: []`). 빈 모듈은 오류가 아니다
- `include[]=items`로 항목이 함께 오지만, 항목이 많으면 `items` 키가 빠질 수 있다(Canvas 문서).
  그때는 `items_url` 경로로 따로 받는다 — `needs_items`가 그 모듈을 가린다
"""

import logging
from dataclasses import dataclass
from typing import Any

from app.lms.parse import is_canvas_id

logger = logging.getLogger(__name__)

NO_NAME = "주차 미정"  # 이름이 빈 모듈. 알림 문구에 그대로 쓴다
NO_TITLE = "(제목 없음)"


@dataclass(frozen=True)
class CanvasModuleItem:
    """저장 직전의 주차 항목 하나. `lms_module_items` 칸과 같은 이름이다."""

    canvas_item_id: int
    module_name: str
    title: str
    item_type: str | None
    html_url: str | None


def needs_items(module: Any) -> int | None:
    """항목이 함께 오지 않은 모듈의 번호. 따로 받아야 한다(없으면 None)."""
    if not isinstance(module, dict) or "items" in module:
        return None
    number = module.get("id")
    return number if is_canvas_id(number) else None


def module_items(
    modules: list[Any], *, extra: dict[int, list[Any]] | None = None
) -> list[CanvasModuleItem]:
    """모듈 목록 응답을 저장할 값으로. `extra`는 따로 받아 온 모듈별 항목이다."""
    items: list[CanvasModuleItem] = []
    for module in modules:
        if not isinstance(module, dict):
            continue
        name = (module.get("name") or "").strip() or NO_NAME
        raw = module.get("items")
        if raw is None and extra is not None and is_canvas_id(module.get("id")):
            raw = extra.get(module["id"])
        for one in raw or []:
            parsed = item(one, module_name=name)
            if parsed is not None:
                items.append(parsed)
    return items


def item(raw: Any, *, module_name: str) -> CanvasModuleItem | None:
    """항목 하나. 번호가 없으면 None이다(번호가 같은 항목인지 가리는 유일한 기준이다)."""
    if not isinstance(raw, dict) or not is_canvas_id(raw.get("id")):
        return None
    kind = raw.get("type")
    return CanvasModuleItem(
        canvas_item_id=raw["id"],
        module_name=module_name,
        title=(raw.get("title") or "").strip() or NO_TITLE,
        item_type=kind if isinstance(kind, str) and kind else None,
        html_url=raw.get("html_url") if isinstance(raw.get("html_url"), str) else None,
    )
