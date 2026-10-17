"""web 타입(`web/src/types/*.ts`)과 API 응답 모델의 칸 이름이 같은지 본다.

정한 규칙: "응답 모델 이름은 `web/src/types/api.ts`와 같게 한다". 이름이 어긋나면 목을 실제
호출로 바꾸는 순간 화면이 빈칸을 그린다(F-14에서 `module_name`·`html_url`이 그랬다).

안에 든 묶음까지 본다: `course.id`·`module_items[].module_name`처럼 길로 펴서 비교한다.
타입·null 여부는 보지 않는다(그건 화면 쪽 typecheck가 잡는다).

web 폴더가 없는 환경(배포 이미지 등)에서는 건너뛴다.
"""

import re
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.main import create_app

WEB_TYPES = Path(__file__).resolve().parents[2] / "web" / "src" / "types"

pytestmark = pytest.mark.skipif(not WEB_TYPES.is_dir(), reason="web 폴더가 없어서 건너뜀")

# (web 타입 이름, API 응답 모델 이름). 화면이 실제 API로 받는 것만 적는다
PAIRS = [
    ("Me", "Me"),
    ("Settings", "Settings"),
    ("LmsConnection", "ConnectionView"),
    ("LmsConnectResult", "ConnectResult"),
    ("Course", "CourseItem"),
    ("CourseDetail", "CourseDetail"),
    ("Assignment", "AssignmentItem"),
    ("LmsSyncResult", "LmsSyncResult"),
    ("SyncStarted", "SyncStarted"),
    ("SyncSkipped", "SyncSkipped"),
    ("FileUploadResult", "FileUploadResult"),
    ("SyllabusItemView", "SyllabusItemView"),
    ("SyllabusExtractResult", "SyllabusExtractResult"),
    ("SyllabusConfirmResult", "SyllabusConfirmResult"),
]
# `GET /lms/updates`는 종류별로 모양이 다르다(web은 합집합 하나로 적는다)
UPDATE_PAIRS = [("module_item", "ModuleItemUpdate"), ("assignment", "AssignmentUpdate")]


def _text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(WEB_TYPES.glob("*.ts")))


def _strip_comments(body: str) -> str:
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return "\n".join(line.split("//")[0] for line in body.split("\n"))


def _segments(body: str) -> list[str]:
    """`;`(묶음 바깥)로 끊어 "이름: 값" 토막들로 만든다."""
    found, buffer, depth = [], "", 0
    for char in body:
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        if char == ";" and depth == 0:
            found.append(buffer)
            buffer = ""
            continue
        buffer += char
    return found + [buffer]


def _ts_paths(body: str, prefix: str = "", text: str | None = None) -> set[str]:
    """칸 이름을 길로 펴서 모은다(묶음은 `a.b`, 묶음 배열은 `a[].b`).

    값이 따로 적은 타입 이름이면(`SyllabusItemView[]`) 그 타입을 찾아 들어간다 — 그러지 않으면
    공통 타입으로 빼낸 칸들이 대조에서 조용히 빠진다.
    """
    source = text if text is not None else _text()
    found: set[str] = set()
    for segment in _segments(_strip_comments(body)):
        match = re.match(r"\s*(\w+)\??:\s*(.*)$", segment, re.S)
        if match is None:
            continue
        name, value = match.group(1), match.group(2)
        found.add(prefix + name)
        if "{" in value:
            inner, rest = _braced(value)
            found |= _ts_paths(
                inner, f"{prefix}{name}{'[]' if rest.lstrip().startswith('[]') else ''}.", source
            )
            continue
        named = re.match(r"\s*([A-Z]\w*)(\[\])?\s*$", value.strip().rstrip(";"))
        if named is None:
            continue
        inner = _ts_interface(source, named.group(1), required=False)
        if inner is not None:
            found |= _ts_paths(inner, f"{prefix}{name}{'[]' if named.group(2) else ''}.", source)
    return found


def _braced(value: str) -> tuple[str, str]:
    """`{ ... }` 안쪽과 그 뒤에 남은 것(배열인지 보려고)."""
    start, depth = value.index("{"), 0
    for index in range(start, len(value)):
        depth += (value[index] == "{") - (value[index] == "}")
        if depth == 0:
            return value[start + 1 : index], value[index + 1 :]
    raise AssertionError("묶음이 닫히지 않았어요")


def _ts_interface(text: str, name: str, *, required: bool = True) -> Any:
    """그 이름의 interface 안쪽. 없으면 None이다(타입 별칭·열거형은 들어갈 것이 없다)."""
    body = re.search(rf"export interface {name} \{{(.*?)\n\}}", text, re.S)
    if body is None:
        assert not required, f"web 타입 {name}을 찾지 못했어요"
        return None
    return body.group(1)


def _ts_union(text: str, kind: str) -> str:
    body = re.search(r"export type LmsUpdate =(.*?)export interface LmsUpdateList", text, re.S)
    assert body is not None
    return next(one for one in body.group(1).split("| {") if f'type: "{kind}"' in one)


def _api_paths(schemas: dict[str, Any], schema: dict[str, Any], prefix: str = "") -> set[str]:
    """OpenAPI 스키마를 같은 꼴의 길로 펴낸다($ref를 따라 내려간다)."""
    found: set[str] = set()
    for name, raw in schema.get("properties", {}).items():
        found.add(prefix + name)
        inner, array = _unwrap(schemas, raw)
        if inner is not None:
            found |= _api_paths(schemas, inner, f"{prefix}{name}{'[]' if array else ''}.")
    return found


def _unwrap(schemas: dict[str, Any], raw: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    """그 칸이 묶음(또는 묶음 배열)이면 그 스키마와 배열인지를 돌려준다."""
    for branch in raw.get("anyOf", [raw]):  # null 가능 칸은 anyOf로 온다
        if "$ref" in branch:
            found = schemas[branch["$ref"].rsplit("/", 1)[1]]
            return (found, False) if found.get("properties") else (None, False)
        if branch.get("type") == "array":
            inner, _ = _unwrap(schemas, branch.get("items", {}))
            if inner is not None:
                return inner, True
        if branch.get("properties"):
            return branch, False
    return None, False


@pytest.fixture(scope="module")
def schemas() -> dict[str, Any]:
    spec = create_app(Settings(_env_file=None)).openapi()  # type: ignore[call-arg]
    return spec["components"]["schemas"]


@pytest.mark.parametrize(("ts_name", "api_name"), PAIRS)
def test_the_web_type_has_the_same_fields(
    schemas: dict[str, Any], ts_name: str, api_name: str
) -> None:
    mine = _ts_paths(_ts_interface(_text(), ts_name))
    assert mine == _api_paths(schemas, schemas[api_name])


@pytest.mark.parametrize(("kind", "api_name"), UPDATE_PAIRS)
def test_the_update_union_matches(schemas: dict[str, Any], kind: str, api_name: str) -> None:
    mine = _ts_paths(_ts_union(_text(), kind))
    assert mine == _api_paths(schemas, schemas[api_name])
