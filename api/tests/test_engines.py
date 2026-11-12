"""엔진 등록부가 코드와 같은지 본다(오케스트레이션 명세 v1 2장·3.1·3.3, O2).

등록부(app/engines/registry.py)는 엔진 모듈을 가져오지 않는 글자 표다. 그래서 엔진 코드의 도구 이름·시간 상한·
판정 버전·모델 설정이 바뀌면 이 시험이 등록부도 같이 고치라고 알려 준다.
"""

import importlib

from app.config import Settings
from app.crawl import importer
from app.crawl import link as notice_link
from app.crawl import service as notice_service
from app.eligibility import ENGINE_VERSION
from app.engines import (
    ENGINES,
    ReviewCode,
    ReviewReason,
    get_engine,
    model_name,
    review_codes,
    review_texts,
)
from app.extraction.models import Limits
from app.extraction.prompt import tool_specs
from app.lms import announce, classify
from app.materials import service as material_service
from app.materials.summarize import TIMEOUT_SECONDS as SUMMARY_SECONDS
from app.posters import service as poster_service
from app.posters.extract import TIMEOUT_SECONDS as POSTER_SECONDS
from app.posters.prompt import SUBMIT_POSTER
from app.prepare import guide
from app.prepare import service as prepare_service
from app.pricing import PRICES
from app.syllabi import service as syllabus_service
from app.syllabi.extract import TIMEOUT_SECONDS as SYLLABUS_SECONDS
from app.syllabi.prompt import EXTRACT_SPEC

# 실행 기록에 엔진 도장을 찍는 곳(O2). 엔진이 여럿인 흐름은 자식, 엔진 하나뿐인 흐름은 뿌리에 찍는다
STAMPED = {
    importer.ENGINE,  # A안 공지 추출(뿌리)·B안 공지 링크(자식)
    announce.CLASSIFY_ENGINE,  # LMS 동기화의 공지 분류(자식)
    announce.EXTRACT_ENGINE,  # LMS 동기화의 기회성 공지 요건 추출(자식)
    poster_service.ENGINE,
    syllabus_service.ENGINE,
    material_service.ENGINE,
    prepare_service.ENGINE,
}


def test_the_registry_lists_the_sixteen_engines_of_the_spec_in_order() -> None:
    """명세 v1 2장 표와 같은 엔진, 같은 순서(수집 → 이해 → 검증 → 판정 → 실행)다."""
    assert list(ENGINES) == [
        "collect.notice",
        "collect.youth",
        "collect.lms",
        "classify.announcement",
        "extract.requirements",
        "read.vision",
        "extract.youth",
        "extract.poster",
        "extract.syllabus",
        "summarize.material",
        "validate.submission",
        "judge.eligibility",
        "guide.documents",
        "plan.backward",
        "act.calendar",
        "act.notify",
    ]
    assert all(spec.id == key for key, spec in ENGINES.items())
    order = ["collect", "understand", "validate", "judge", "act"]
    layers = [order.index(spec.layer) for spec in ENGINES.values()]
    assert layers == sorted(layers)


def test_the_judge_keeps_its_engine_version_and_the_rest_start_at_one() -> None:
    assert ENGINES["judge.eligibility"].version == ENGINE_VERSION
    assert {spec.version for key, spec in ENGINES.items() if key != "judge.eligibility"} == {1}


def test_llm_engines_name_a_priced_model_setting_that_matches_their_tier() -> None:
    """모델 이름은 등록부에 없고 설정이 정한다. 기본 모델은 단가표에 있고, lite 등급이면 Flash-Lite다."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    llm = [spec for spec in ENGINES.values() if spec.uses_llm]
    assert [spec.id for spec in llm] == [
        "classify.announcement",
        "extract.requirements",
        "read.vision",
        "extract.poster",
        "extract.syllabus",
        "summarize.material",
        "guide.documents",
    ]  # 명세 v1 2장: LLM을 쓰는 엔진은 7개, 모델이 도구를 고르는 것은 하나
    assert [spec.id for spec in llm if spec.kind == "llm_loop"] == ["extract.requirements"]
    for spec in llm:
        model = model_name(spec, settings)
        assert model is not None and ("google", model) in PRICES, spec.id
        assert ("lite" in model) == (spec.tier == "lite"), spec.id
    for spec in ENGINES.values():
        if not spec.uses_llm:
            assert (spec.tier, spec.model_setting, spec.tools) == ("none", None, ()), spec.id
            assert model_name(spec, settings) is None
        assert spec.escalate_to is None  # 캐스케이드는 O4에서 켠다


def test_the_tools_the_model_sees_are_the_ones_in_the_registry() -> None:
    assert ENGINES["extract.requirements"].tools == tuple(
        spec.name for spec in tool_specs(Limits())
    )
    assert ENGINES["classify.announcement"].tools == (classify.SUBMIT_ANNOUNCEMENT.name,)
    assert ENGINES["extract.poster"].tools == (SUBMIT_POSTER.name,)
    assert ENGINES["extract.syllabus"].tools == (EXTRACT_SPEC.name,)
    assert ENGINES["guide.documents"].tools == (guide.TOOL.name,)
    assert ENGINES["summarize.material"].tools == ()  # 도구 없이 글로 답한다


def test_the_time_limits_are_the_ones_in_the_code() -> None:
    assert ENGINES["collect.notice"].timeout_s == notice_link.TOTAL_TIMEOUT
    assert ENGINES["classify.announcement"].timeout_s == classify.TIMEOUT_SECONDS
    assert ENGINES["extract.requirements"].timeout_s == notice_service.MODEL_SECONDS
    assert ENGINES["extract.poster"].timeout_s == POSTER_SECONDS
    assert ENGINES["extract.syllabus"].timeout_s == SYLLABUS_SECONDS
    assert ENGINES["summarize.material"].timeout_s == SUMMARY_SECONDS
    assert ENGINES["guide.documents"].timeout_s == guide.TIMEOUT_SECONDS


def test_the_contract_types_and_the_code_modules_exist() -> None:
    """입출력 타입은 "모듈:이름" 글자다. 이름을 바꾸면 여기서 걸린다(None은 아직 고정한 타입이 없는 경계)."""
    for spec in ENGINES.values():
        importlib.import_module(spec.code)
        for name in (spec.input_type, spec.output_type):
            if name is None:
                continue
            module, _, attr = name.partition(":")
            assert isinstance(getattr(importlib.import_module(module), attr), type), name


def test_every_llm_engine_but_the_vision_sub_tool_is_stamped_on_a_run() -> None:
    """LLM을 쓰는 엔진은 실행 기록에서 따로 센다. read.vision만 요건 추출 안의 하위 도구라 그 실행에 붙는다."""
    assert STAMPED <= set(ENGINES)
    llm = {spec.id for spec in ENGINES.values() if spec.uses_llm}
    assert llm - STAMPED == {"read.vision"}
    assert STAMPED <= llm


def test_shared_output_engines_are_the_ones_many_students_see() -> None:
    """공유 산출물(공고·요건·공지 갈래)을 만드는 엔진의 실행에는 user_id를 남기지 않는다(명세 v1 6장 5번)."""
    shared = {spec.id for spec in ENGINES.values() if spec.shared_output}
    assert {"extract.requirements", "classify.announcement", "collect.notice"} <= shared
    assert not shared & {"extract.poster", "extract.syllabus", "summarize.material"}
    assert not shared & {"guide.documents", "judge.eligibility", "collect.lms"}


def test_an_unknown_engine_is_a_key_error() -> None:
    assert get_engine("extract.poster") is ENGINES["extract.poster"]
    try:
        get_engine("extract.everything")
    except KeyError as exc:
        assert "extract.everything" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("모르는 엔진을 받아들였다")


def test_the_review_codes_are_the_table_of_the_spec() -> None:
    assert [code.value for code in ReviewCode] == [
        "NO_SUBMISSION",
        "REPAIRED",
        "LOW_CONFIDENCE",
        "NOT_READ",
        "READ_CAP",
        "TOKEN_CAP",
        "MODEL_FLAG",
        "AMBIGUOUS",
        "UNREADABLE",
        "PARTIAL_READ",
        "MISSING_FILE",
    ]


def test_codes_and_texts_are_kept_once_in_first_order() -> None:
    """문구는 지금 review_reasons처럼 같은 글을 한 번만, 코드는 같은 코드를 한 번만 남긴다."""
    reasons = [
        ReviewReason(ReviewCode.PARTIAL_READ, "첨부 '가.pdf' 1/3쪽만 읽음"),
        ReviewReason(ReviewCode.PARTIAL_READ, "첨부 '나.pdf' 2/3쪽만 읽음"),
        ReviewReason(ReviewCode.REPAIRED, "AI가 정리한 조건을 확신하지 못함"),
        ReviewReason(ReviewCode.LOW_CONFIDENCE, "AI가 정리한 조건을 확신하지 못함"),
    ]
    assert review_texts(reasons) == (
        "첨부 '가.pdf' 1/3쪽만 읽음",
        "첨부 '나.pdf' 2/3쪽만 읽음",
        "AI가 정리한 조건을 확신하지 못함",
    )
    assert review_codes(reasons) == ("PARTIAL_READ", "REPAIRED", "LOW_CONFIDENCE")
    assert all(type(code) is str for code in review_codes(reasons))  # DB에는 글자로 넣는다
