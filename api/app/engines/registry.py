"""엔진 등록부(오케스트레이션 명세 v1 2장·3.1, O2).

엔진마다 이름(id)·버전·계층·종류·모델 등급·모델에 보이는 도구·입출력 타입·시간 상한·평가 세트를 한 곳에 둔다.
실행 기록의 agent_runs.engine·engine_version이 이 표의 id·version이고, 엔진별 지표·평가(O3)가 그 값으로 묶는다.

- **버전**은 프롬프트·도구 스키마·검증 규칙·상한이 바뀌면 1 올린다. 이 표가 처음 생긴 판(O2)은 모두 1이고,
  판정만 이미 있던 ENGINE_VERSION(6)을 그대로 쓴다.
- **모델 이름은 여기 적지 않는다.** 등급(tier)과 그 모델을 정하는 설정 이름(model_setting)만 적는다 —
  비교 실험이 설정만 바꿔 끼울 수 있게(model_name).
- **입출력 타입**은 "모듈:이름" 글자다. 이 모듈이 엔진 모듈을 가져오지 않아야 실행 기록(agent_log)이 이 표를 써도
  순환 import가 없다. 아직 고정한 타입이 없는 경계(인자 여러 개·dict 묶음)는 None이다 — 흐름 실행기(O5)에서 만든다.
- **shared_output**이 참인 엔진의 실행은 user_id를 남기지 않는다(명세 6장 5번) — 결과를 여러 학생이 본다.
- 이 표가 코드와 같은지(도구 이름·시간 상한·판정 버전·모델 설정·타입·모듈)는 tests/test_engines.py가 본다.
  엔진 코드를 고치면 그 시험이 이 표를 같이 고치라고 알려 준다.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.config import Settings

# 계층: 수집 → 이해 → 검증 → 판정 → 실행(명세 v1 2장)
Layer = Literal["collect", "understand", "validate", "judge", "act"]
EngineKind = Literal["llm_loop", "llm_single", "code", "external"]
Tier = Literal["none", "lite", "standard"]  # lite = Flash-Lite, standard = Flash(LLM_모델_선정.md)
EvalSuite = Literal[
    "EV-JUDGE",
    "EV-EXTRACT",
    "EV-POSTER",
    "EV-CLASSIFY",
    "EV-SYLLABUS",
    "EV-GUIDE",
    "EV-PLAN",
    "EV-SUMMARY",
    "E2E",  # 따로 세트가 없는 엔진(수집·실행)은 흐름 시나리오(S01–S23)로 본다
]


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 1  # 1이면 다시 하지 않는다
    on: tuple[str, ...] = ()  # 다시 할 오류 코드. 예: ("LLM_TIMEOUT",)
    backoff_s: float = 0.0


@dataclass(frozen=True)
class EngineSpec:
    id: str  # "extract.requirements" — 실행 기록·지표·평가의 키
    version: int
    layer: Layer
    kind: EngineKind
    tier: Tier  # 기본 모델 등급. 실제 모델 이름은 설정(model_setting)이 정한다
    model_setting: str | None  # 모델 이름을 정하는 Settings 칸. LLM을 쓰지 않으면 None
    tools: tuple[str, ...]  # 모델에 보이는 도구 이름(tool_calls.tool_name과 같다)
    input_type: str | None  # "모듈:이름". 아직 고정한 타입이 없으면 None
    output_type: str | None
    timeout_s: float | None  # 엔진 한 번을 기다리는 초. 상한이 없으면 None
    shared_output: bool  # 결과를 여러 학생이 보는가(공고·요건·공지 갈래). 참이면 실행에 user_id를 남기지 않는다
    eval_suite: EvalSuite  # 명세 7장 평가 세트
    code: str  # 지금 코드(모듈)
    escalate_to: Tier | None = None  # 캐스케이드 위 등급(명세 5.4, O4). 지금은 모두 없다
    retry: RetryPolicy = RetryPolicy()

    @property
    def uses_llm(self) -> bool:
        return self.kind in ("llm_loop", "llm_single")


def _spec(**values: object) -> tuple[str, EngineSpec]:
    spec = EngineSpec(**values)  # type: ignore[arg-type]
    return spec.id, spec


# 명세 v1 2장 표와 같은 순서다(수집 → 이해 → 검증 → 판정 → 실행)
ENGINES: dict[str, EngineSpec] = dict(
    (
        _spec(
            id="collect.notice",
            version=1,
            layer="collect",
            kind="external",
            tier="none",
            model_setting=None,
            tools=(),
            input_type="app.crawl.link:NoticeLink",
            output_type="app.crawl.link:LinkedNotice",
            timeout_s=60.0,  # 요청 하나(파일까지)의 전체 초
            shared_output=True,
            eval_suite="E2E",
            code="app.crawl.link",
        ),
        _spec(
            id="collect.youth",
            version=1,
            layer="collect",
            kind="external",
            tier="none",
            model_setting=None,
            tools=(),
            input_type=None,
            output_type="app.youth.client:FetchResult",
            timeout_s=None,
            shared_output=True,
            eval_suite="E2E",
            code="app.youth.client",
        ),
        _spec(
            id="collect.lms",
            version=1,
            layer="collect",
            kind="external",
            tier="none",
            model_setting=None,
            tools=(),
            input_type=None,
            output_type=None,
            timeout_s=None,
            shared_output=False,
            eval_suite="E2E",
            code="app.lms.client",
        ),
        _spec(
            id="classify.announcement",
            version=1,
            layer="understand",
            kind="llm_single",
            tier="lite",
            model_setting="classify_model",
            tools=("submit_announcement",),
            input_type=None,  # 지금은 인자 셋(제목·본문·게시일). AnnouncementInput은 O5에서
            output_type="app.lms.classify:Classified",
            timeout_s=30.0,
            shared_output=True,  # 갈래는 그 과목 수강생 모두의 할 일·알림·공고가 된다
            eval_suite="EV-CLASSIFY",
            code="app.lms.classify",
        ),
        _spec(
            id="extract.requirements",
            version=1,
            layer="understand",
            kind="llm_loop",
            tier="standard",
            model_setting="extraction_model",
            tools=(
                "read_attachment_text",
                "read_attachment_image",
                "fetch_original",
                "submit_requirements",
            ),
            input_type="app.extraction.models:NoticeInput",
            output_type="app.extraction.models:ExtractionResult",
            timeout_s=120.0,  # 학교 공지 링크(B안)가 모델을 기다리는 초
            shared_output=True,
            eval_suite="EV-EXTRACT",
            code="app.extraction.agent",
        ),
        _spec(
            id="read.vision",
            version=1,
            layer="understand",
            kind="llm_single",
            tier="standard",
            model_setting="vision_model",
            tools=(),  # 요건 추출의 read_attachment_image 안에서 부르는 하위 도구다
            input_type=None,
            output_type=None,
            timeout_s=None,
            shared_output=True,
            eval_suite="EV-EXTRACT",
            code="app.extraction.agent",
        ),
        _spec(
            id="extract.youth",
            version=1,
            layer="understand",
            kind="code",
            tier="none",
            model_setting=None,
            tools=(),
            input_type=None,
            output_type="app.youth.convert:PolicyRecord",
            timeout_s=None,
            shared_output=True,
            eval_suite="E2E",
            code="app.youth.convert",
        ),
        _spec(
            id="extract.poster",
            version=1,
            layer="understand",
            kind="llm_single",
            tier="standard",
            model_setting="vision_model",
            tools=("submit_poster",),
            input_type="app.llm:Blob",
            output_type="app.schemas.posters:PosterDraft",
            timeout_s=50.0,
            shared_output=False,  # 초안은 올린 학생만 본다(등록하면 공고가 되지만 그건 확인 단계다)
            eval_suite="EV-POSTER",
            code="app.posters.extract",
        ),
        _spec(
            id="extract.syllabus",
            version=1,
            layer="understand",
            kind="llm_single",
            tier="standard",
            model_setting="extraction_model",
            tools=("save_syllabus_items",),
            input_type=None,
            output_type="app.syllabi.extract:Extracted",
            timeout_s=50.0,
            shared_output=False,
            eval_suite="EV-SYLLABUS",
            code="app.syllabi.extract",
        ),
        _spec(
            id="summarize.material",
            version=1,
            layer="understand",
            kind="llm_single",
            tier="lite",
            model_setting="summary_model",
            tools=(),  # 도구 없이 글로 답한다
            input_type=None,
            output_type=None,
            timeout_s=55.0,
            shared_output=False,
            eval_suite="EV-SUMMARY",
            code="app.materials.summarize",
        ),
        _spec(
            id="validate.submission",
            version=1,
            layer="validate",
            kind="code",
            tier="none",
            model_setting=None,
            tools=(),
            input_type="app.extraction.validate:Context",
            output_type="app.extraction.validate:Submission",
            timeout_s=None,
            shared_output=True,
            eval_suite="EV-EXTRACT",
            code="app.extraction.validate",
        ),
        _spec(
            id="judge.eligibility",
            version=6,  # app.eligibility.ENGINE_VERSION
            layer="judge",
            kind="code",
            tier="none",
            model_setting=None,
            tools=(),
            input_type="app.eligibility:Profile",  # × Requirement[]. 프로필은 이 엔진만 받는다
            output_type="app.eligibility:Judgment",
            timeout_s=None,
            shared_output=False,
            eval_suite="EV-JUDGE",
            code="app.eligibility.engine",
        ),
        _spec(
            id="guide.documents",
            version=1,
            layer="act",
            kind="llm_single",
            tier="lite",
            model_setting="guide_model",
            tools=("submit_document_guides",),  # 서류 사전에 없는 것만 묻는다
            input_type=None,
            output_type="app.prepare.guide:GuideDraft",
            timeout_s=60.0,
            shared_output=False,
            eval_suite="EV-GUIDE",
            code="app.prepare.guide",
        ),
        _spec(
            id="plan.backward",
            version=1,
            layer="act",
            kind="code",
            tier="none",
            model_setting=None,
            tools=(),
            input_type="app.prepare.plan:PlanDocument",
            output_type="app.prepare.plan:TaskDraft",
            timeout_s=None,
            shared_output=False,
            eval_suite="EV-PLAN",
            code="app.prepare.plan",
        ),
        _spec(
            id="act.calendar",
            version=1,
            layer="act",
            kind="external",
            tier="none",
            model_setting=None,
            tools=(),
            input_type=None,
            output_type=None,
            timeout_s=None,
            shared_output=False,
            eval_suite="E2E",
            code="app.calendar.google",
        ),
        _spec(
            id="act.notify",
            version=1,
            layer="act",
            kind="external",
            tier="none",
            model_setting=None,
            tools=(),
            input_type=None,
            output_type=None,
            timeout_s=None,
            shared_output=False,
            eval_suite="E2E",
            code="app.push.send",
        ),
    )
)


def get_engine(engine_id: str) -> EngineSpec:
    """등록부의 엔진. 없는 id면 KeyError다(실행 기록에 모르는 엔진 이름이 남지 않게)."""
    try:
        return ENGINES[engine_id]
    except KeyError:
        raise KeyError(f"등록부에 없는 엔진이에요: {engine_id}") from None


def model_name(spec: EngineSpec, settings: "Settings") -> str | None:
    """이 엔진이 지금 쓰는 모델 이름(설정값). LLM을 쓰지 않는 엔진이면 None이다."""
    if spec.model_setting is None:
        return None
    return str(getattr(settings, spec.model_setting))
