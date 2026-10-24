"""Cloud Run 배포 계획(docs/배포_절차.md). 설정(api/.env)에서 비밀값·환경 변수·gcloud 인자를 만든다.

여기는 계산만 하고 gcloud를 부르지 않는다(부르는 곳은 cloudrun.py). 배포 서버의 설정은 로컬 `api/.env`와
같은 값에서 출발하고, 배포에서 정하는 값(CORS·스케줄러)만 바꾼다. 시험용으로만 바꾸는 주소는 넘기지 않는다
— 로컬 `.env`가 녹화 응답이나 가짜 저장소를 가리켜도 배포 서버는 진짜 주소(기본값)를 쓴다.

지키는 것:
- 비밀값은 Secret Manager로만 보내고 환경 변수 파일에는 넣지 않는다. 화면에는 이름과 길이만 찍는다
- 인스턴스는 **최대 1개**다. 서버 안 스케줄러가 돌기 때문이다(워커가 둘이면 같은 일이 두 번 돈다. 새 버전을 올리는 동안만 잠깐 2개가 겹친다)
- **CPU를 늘 준다**(`--no-cpu-throttling`, 인스턴스 기준 과금). 준비하기·포스터·강의자료 요약은 202로 답한
  뒤 같은 프로세스에서 계속 돈다(app/background.py) — 요청 사이에 CPU를 끊으면 멈춘다
"""

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from psycopg.conninfo import conninfo_to_dict

from app.auth import auth_settings_problem
from app.config import Settings
from app.crypto import encrypt
from app.push.keys import load_keys
from app.uploads.storage import storage_settings_problem

SERVICE = "unipivot-api"
REGION = "asia-northeast3"  # 서울. Supabase(ap-northeast-2)·Vercel 함수(icn1)와 같은 도시다
SERVICE_ACCOUNT_ID = "unipivot-api"
CPU = "1"  # 1 vCPU 아래는 요청 기준 과금만 된다(CPU를 늘 줄 수 없다)
MEMORY = "1Gi"  # 강의자료 PDF(300쪽까지)를 메모리에서 읽는다
TIMEOUT_SECONDS = 300

# 켜야 하는 API: Cloud Run·소스 빌드(Cloud Build·Artifact Registry)·비밀값·Gemini. Compute Engine은
# 소스 빌드가 쓰는 기본 서비스 계정({번호}-compute@…)이 이 API를 켜야 생긴다
APIS = (
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "compute.googleapis.com",
)
# 서버(서비스 계정)가 갖는 권한: Gemini 부르기, 비밀값 읽기
SERVICE_ACCOUNT_ROLES = ("roles/aiplatform.user", "roles/secretmanager.secretAccessor")
BUILDER_ROLE = "roles/run.builder"  # 소스 빌드 계정이 이미지를 만들어 올리는 권한

_PROJECT_ID = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_REGION_NAME = re.compile(r"[a-z]+-[a-z]+[0-9]+")
_SERVICE_NAME = re.compile(r"[a-z](?:[-a-z0-9]{0,47}[a-z0-9])?")
# Supabase 직접 연결 주소. IPv6 주소라 Cloud Run(IPv4로 나간다)에서 닿지 않는다
_DIRECT_DB_HOST = re.compile(r"db\.[a-z0-9]+\.supabase\.co")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


@dataclass(frozen=True)
class Secret:
    env: str  # 배포 서버의 환경 변수 이름
    field: str  # Settings의 필드
    secret_id: str  # Secret Manager의 이름


SECRETS = (
    Secret("DATABASE_URL", "database_url", "unipivot-database-url"),
    Secret("TOKEN_ENCRYPTION_KEY", "token_encryption_key", "unipivot-token-encryption-key"),
    Secret("SUPABASE_SECRET_KEY", "supabase_secret_key", "unipivot-supabase-secret-key"),
    Secret("SUPABASE_JWT_SECRET", "supabase_jwt_secret", "unipivot-supabase-jwt-secret"),
    Secret(
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "google_oauth_client_secret",
        "unipivot-google-oauth-client-secret",
    ),
    Secret("VAPID_PRIVATE_KEY", "vapid_private_key", "unipivot-vapid-private-key"),
    Secret("YOUTH_API_KEY", "youth_api_key", "unipivot-youth-api-key"),
    Secret("INTERNAL_API_KEY", "internal_api_key", "unipivot-internal-api-key"),
)
# 로컬 값을 그대로 넘기는 설정(비밀이 아니다). 비어 있으면 넘기지 않는다(기본값과 같다)
COPIED = (
    "supabase_url",
    "supabase_storage_bucket",
    "google_cloud_project",
    "google_cloud_location",
    "extraction_model",
    "vision_model",
    "guide_model",
    "classify_model",
    "summary_model",
    "material_max_tokens",
    "extraction_max_reads",
    "extraction_max_tokens",
    "google_oauth_client_id",
    "vapid_subject",
)
DECIDED = ("cors_origins", "scheduler_enabled")  # 배포에서 정한다
# 배포 서버는 기본값을 쓴다. 시험용으로만 바꾸는 주소와 web이 기대는 경로다
DEFAULTS_ONLY = (
    "google_token_url",
    "google_revoke_url",
    "google_calendar_api_base",
    "supabase_storage_base",
    "lms_api_base",
    "api_prefix",
)


@dataclass(frozen=True)
class Plan:
    project: str
    region: str
    service: str
    origins: tuple[str, ...]
    env: dict[str, str]  # 환경 변수(비밀 아님)
    secrets: tuple[tuple[Secret, str], ...]  # (비밀, 값) — 값이 있는 것만
    min_instances: int | None  # None이면 지금 값을 그대로 둔다(처음 올릴 때는 0)

    @property
    def service_account(self) -> str:
        return service_account(self.project)


def service_account(project: str) -> str:
    return f"{SERVICE_ACCOUNT_ID}@{project}.iam.gserviceaccount.com"


def project_problem(project: str) -> str | None:
    if not project:
        return (
            "GOOGLE_CLOUD_PROJECT가 비어 있어요(api/.env). Gemini를 부르는 프로젝트 ID를 넣으세요"
        )
    if not _PROJECT_ID.fullmatch(project):
        return "GOOGLE_CLOUD_PROJECT가 프로젝트 ID 모양이 아니에요. 콘솔 위쪽의 프로젝트 ID(소문자·숫자·-)를 넣으세요"
    return None


def normalize_origins(raw: list[str]) -> tuple[tuple[str, ...], list[str]]:
    """웹 주소를 CORS 출처 모양(https://호스트)으로 맞춘다. 끝의 /는 떼고, 경로·쿼리가 있으면 막는다.

    CORS는 출처를 글자 그대로 비교한다 — 끝에 /가 붙거나 경로가 들어가면 모든 요청이 막힌다.
    """
    origins: list[str] = []
    problems: list[str] = []
    for value in raw:
        text = value.strip().rstrip("/")
        try:
            parts = urlsplit(text)
        except ValueError:
            parts = None
        if (
            parts is None
            or parts.scheme.lower() != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.path
            or parts.query
            or parts.fragment
            or "*" in text
        ):
            problems.append(
                f"웹 주소가 출처 모양이 아니에요: {text or '(빈 값)'}. "
                "https://<프로젝트>.vercel.app처럼 경로 없이 넣으세요"
            )
            continue
        origin = f"https://{parts.netloc.lower()}"
        if origin not in origins:
            origins.append(origin)
    if not raw:
        problems.append("--web-origin으로 웹 주소를 넣어 주세요(https://<프로젝트>.vercel.app)")
    return tuple(origins), problems


def database_problem(url: str) -> str | None:
    """배포 서버가 닿을 수 있는 DB 주소인지. 값은 보여 주지 않는다."""
    if not url.strip():
        return "DATABASE_URL이 비어 있어요(api/.env)"
    try:
        hosts = conninfo_to_dict(url).get("host") or ""
    except Exception:
        return "DATABASE_URL을 읽지 못했어요(값은 보여 주지 않음). Supabase 대시보드 Connect에서 다시 복사하세요"
    names = [host.strip().lower() for host in str(hosts).split(",")]
    if not any(names) or any(
        not name or name.startswith("/") or name in _LOCAL_HOSTS for name in names
    ):
        return (
            "DATABASE_URL이 이 컴퓨터의 DB를 가리켜요. 배포 서버는 Supabase DB에 붙어야 해요 — "
            "대시보드 Connect의 Session pooler 주소를 넣으세요"
        )
    if any(_DIRECT_DB_HOST.fullmatch(name) for name in names):
        return (
            "DATABASE_URL이 직접 연결(db.<ref>.supabase.co)이에요. 이 주소는 IPv6라 Cloud Run에서 닿지 "
            "않아요 — 대시보드 Connect의 Session pooler 주소(…pooler.supabase.com:5432)를 넣으세요"
        )
    return None


def served(settings: Settings) -> Settings:
    """배포 서버가 갖게 될 설정에서 시험용 값만 기본값으로 돌린 것. 검사는 이것으로 한다 — 로컬 `.env`가
    가짜 저장소(SUPABASE_STORAGE_BASE)를 가리키면 로컬 값으로는 통과해도 서버에서는 진짜 주소를 쓴다."""
    fields = Settings.model_fields
    return settings.model_copy(update={name: fields[name].default for name in DEFAULTS_ONLY})


def problems(settings: Settings) -> list[str]:
    """배포를 막는 설정 문제. 값은 보여 주지 않는다."""
    found: list[str] = []
    settings = served(settings)
    if problem := project_problem(settings.google_cloud_project.strip()):
        found.append(problem)
    if problem := database_problem(settings.database_url):
        found.append(problem)
    if problem := auth_settings_problem(settings):
        found.append(problem)
    if problem := storage_settings_problem(settings):
        found.append(problem)
    try:
        encrypt("check", settings.token_encryption_key)
    except Exception:
        found.append(
            "TOKEN_ENCRYPTION_KEY를 쓸 수 없어요(비었거나 키 모양이 아님). 로컬에서 쓰던 키를 그대로 "
            "넣으세요 — 바꾸면 저장된 Google·LMS 토큰을 못 읽어요"
        )
    return found


def warnings(settings: Settings) -> list[str]:
    """배포는 되지만 기능 하나가 빠지는 것."""
    found: list[str] = []
    if bool(settings.google_oauth_client_id) != bool(settings.google_oauth_client_secret):
        found.append(
            "GOOGLE_OAUTH_CLIENT_ID와 GOOGLE_OAUTH_CLIENT_SECRET 중 하나만 있어요. 캘린더 권한이 55분 뒤 끊겨요"
        )
    elif not settings.google_oauth_client_id:
        found.append("GOOGLE_OAUTH_CLIENT_ID·SECRET이 없어요. 캘린더 권한이 55분 뒤 끊겨요")
    if (
        settings.vapid_private_key
        and load_keys(private_key=settings.vapid_private_key, subject=settings.vapid_subject)
        is None
    ):
        found.append(
            "VAPID 키를 읽지 못했거나 VAPID_SUBJECT가 비었어요. 웹 푸시 없이 알림함에만 쌓여요"
        )
    elif not settings.vapid_private_key:
        found.append("VAPID_PRIVATE_KEY가 없어요. 웹 푸시 없이 알림함에만 쌓여요")
    if not settings.youth_api_key:
        found.append("YOUTH_API_KEY가 없어요. 청년정책 매일 수집(04:00)이 돌지 않아요")
    if not settings.internal_api_key:
        found.append("INTERNAL_API_KEY가 없어요. /internal/*(지표·시나리오 실행)이 모두 403이에요")
    if settings.scheduler_enabled:
        found.append(
            "로컬 .env의 SCHEDULER_ENABLED가 true예요. 배포한 서버와 같은 DB를 쓰니, 배포한 뒤에는 로컬을 "
            "false로 두세요(둘 다 켜면 알림이 두 번 나가요)"
        )
    return found


def defaults_differ(settings: Settings) -> list[str]:
    """로컬 값이 기본값과 달라도 배포 서버에는 넘기지 않는 설정의 환경 변수 이름."""
    fields = Settings.model_fields
    return [
        name.upper() for name in DEFAULTS_ONLY if getattr(settings, name) != fields[name].default
    ]


def _env_text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_plan(
    settings: Settings,
    origins: tuple[str, ...],
    *,
    region: str = REGION,
    service: str = SERVICE,
    min_instances: int | None = None,
) -> Plan:
    env = {
        name.upper(): _env_text(getattr(settings, name))
        for name in COPIED
        if _env_text(getattr(settings, name)).strip()
    }
    env["CORS_ORIGINS"] = json.dumps(list(origins))
    env["SCHEDULER_ENABLED"] = "true"
    secrets = tuple(
        (secret, getattr(settings, secret.field))
        for secret in SECRETS
        if getattr(settings, secret.field)
    )
    return Plan(
        project=settings.google_cloud_project.strip(),
        region=region,
        service=service,
        origins=origins,
        env=env,
        secrets=secrets,
        min_instances=min_instances,
    )


def target_problems(region: str, service: str) -> list[str]:
    found = []
    if not _REGION_NAME.fullmatch(region):
        found.append(f"지역 이름이 이상해요: {region} (예: {REGION})")
    if not _SERVICE_NAME.fullmatch(service):
        found.append(f"서비스 이름이 이상해요: {service} (소문자·숫자·-, 49자까지)")
    return found


def env_file_text(env: dict[str, str]) -> str:
    """gcloud --env-vars-file에 줄 YAML. 값마다 JSON 문자열로 적는다(JSON은 YAML이다, 모두 ASCII)."""
    return "".join(f"{key}: {json.dumps(value)}\n" for key, value in env.items())


def secrets_flag(plan: Plan) -> str:
    return ",".join(f"{secret.env}={secret.secret_id}:latest" for secret, _ in plan.secrets)


def deploy_args(plan: Plan, env_file: str) -> list[str]:
    """`gcloud run deploy` 인자(gcloud는 빼고). api 폴더에서 돌린다(--source .).

    `--min-instances`는 넣으라고 할 때만 붙인다. 안 붙이면 지금 값을 그대로 둔다 — 데모 기간(1)에 다시
    올리다가 평소(0)로 돌아가지 않게.
    """
    args = [
        "run",
        "deploy",
        plan.service,
        f"--project={plan.project}",
        f"--region={plan.region}",
        "--source=.",
        f"--service-account={plan.service_account}",
        f"--cpu={CPU}",
        f"--memory={MEMORY}",
        "--no-cpu-throttling",
        "--cpu-boost",
        "--max-instances=1",
    ]
    if plan.min_instances is not None:
        args.append(f"--min-instances={plan.min_instances}")
    args += [
        f"--timeout={TIMEOUT_SECONDS}",
        "--allow-unauthenticated",
        f"--env-vars-file={env_file}",
        f"--set-secrets={secrets_flag(plan)}",
        "--quiet",
    ]
    return args
