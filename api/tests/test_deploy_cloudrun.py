"""Cloud Run 배포 명령(app/deploy). gcloud는 가짜로 바꾼다 — 부른 인자·표준 입력만 본다.

값은 모두 시험용 모양이다(실제 키·주소가 아니다).
"""

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.deploy import cloudrun
from app.deploy import plan as deploy_plan
from app.deploy.cloudrun import DeployError, Result
from app.push.keys import generate_keys

API_DIR = Path(__file__).resolve().parents[1]
PROJECT = "unipivot-demo-123"
SUPABASE = "https://abcdefghijklmnopqrst.supabase.co"
POOLER_DB = (
    "postgresql://postgres.abcdefghijklmnopqrst:Pw-for-tests-9@"
    "aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres"
)
STORAGE_KEY = "sb_secret_" + "Xy7" * 10 + "c"
WEB = "https://unipivot-demo.vercel.app"
URL = "https://unipivot-api-abc123-du.a.run.app"
VAPID_PRIVATE, _ = generate_keys()
SECRET_VALUES = {
    "database_url": POOLER_DB,
    "token_encryption_key": Fernet.generate_key().decode(),
    "supabase_secret_key": STORAGE_KEY,
    "google_oauth_client_secret": "GOCSPX-test-client-secret-value",
    "vapid_private_key": VAPID_PRIVATE,
    "youth_api_key": "youth-test-key-0000",
    "internal_api_key": "internal-test-key-0000-0000",
}


def full_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        **SECRET_VALUES,
        "supabase_url": SUPABASE,
        "google_cloud_project": PROJECT,
        "google_oauth_client_id": "1234-test.apps.googleusercontent.com",
        "vapid_subject": "mailto:team@example.com",
        "scheduler_enabled": False,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def leaked(text: str) -> list[str]:
    """출력이나 인자에 들어간 비밀값(있으면 안 된다)."""
    return [name for name, value in SECRET_VALUES.items() if value in text]


class FakeGcloud:
    """부른 gcloud 인자·표준 입력을 적는다. `answer`가 (인자, 입력)에 답한다(없으면 성공)."""

    def __init__(
        self,
        answer: Callable[[list[str], bytes | None], Result] | None = None,
        *,
        logged_in: bool = True,
    ) -> None:
        self.calls: list[tuple[list[str], bytes | None, bool]] = []
        self._answer = answer
        self._accounts = [{"account": "me@example.com", "status": "ACTIVE"}] if logged_in else []

    def __call__(
        self, args: Sequence[str], *, input: bytes | None = None, capture: bool = True
    ) -> Result:
        call = list(args)
        if call[:2] == ["auth", "list"]:  # 로그인 확인은 적지 않는다(바꾸는 일이 아니다)
            return Result(0, json.dumps(self._accounts).encode())
        self.calls.append((call, input, capture))
        if self._answer is not None:
            return self._answer(call, input)
        return Result(0)

    def commands(self) -> list[list[str]]:
        return [call for call, _, _ in self.calls]

    def find(self, *prefix: str) -> list[tuple[list[str], bytes | None, bool]]:
        return [entry for entry in self.calls if entry[0][: len(prefix)] == list(prefix)]


def refuse(call: list[str], _: bytes | None) -> Result:
    raise AssertionError(f"gcloud를 불렀어요: {call}")


def not_found(what: str = "Secret") -> Result:
    return Result(
        1, stderr=f"ERROR: (gcloud) NOT_FOUND: {what} not found or has no versions.".encode()
    )


def described_url(call: list[str]) -> Result | None:
    if call[:3] == ["run", "services", "describe"]:
        return Result(0, json.dumps({"status": {"url": URL}}).encode())
    return None


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    for name in ("Dockerfile", "pyproject.toml", "uv.lock", ".python-version"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    for name in (".dockerignore", ".gcloudignore"):
        (tmp_path / name).write_text(".venv\n.env\n", encoding="utf-8")
    (tmp_path / "app").mkdir()
    return tmp_path


def run_main(argv: list[str], **kwargs: object) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = cloudrun.main(argv, out=lines.append, sleep=lambda _: None, **kwargs)  # type: ignore[arg-type]
    return code, lines


# --- 계획 ----------------------------------------------------------------------------------------


def test_every_setting_has_a_place() -> None:
    """새 설정을 더하면 배포에서 넘길지(그대로·비밀값·배포에서 정함·기본값) 정해야 이 시험이 지난다."""
    groups = [
        set(deploy_plan.COPIED),
        set(deploy_plan.DECIDED),
        set(deploy_plan.DEFAULTS_ONLY),
        {secret.field for secret in deploy_plan.SECRETS},
    ]
    assert set().union(*groups) == set(Settings.model_fields)
    assert sum(len(group) for group in groups) == len(Settings.model_fields)  # 겹치지 않는다


def test_the_server_reads_back_what_we_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """환경 변수 이름이 틀리면 서버가 조용히 기본값을 쓴다. 보낸 값을 Settings로 다시 읽어 맞춰 본다."""
    local = full_settings(
        lms_api_base="http://127.0.0.1:9999",  # 녹화 응답 재생용(시험용)
        google_token_url="http://127.0.0.1:9998/token",
        material_max_tokens=12_345,
        guide_model="gemini-3.8-flash",
    )
    plan = deploy_plan.build_plan(local, (WEB, "https://www.example.com"))
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    for key, value in plan.env.items():
        monkeypatch.setenv(key, value)
    for secret, value in plan.secrets:
        monkeypatch.setenv(secret.env, value)

    served = Settings(_env_file=None)  # type: ignore[call-arg]

    for field in deploy_plan.COPIED:
        assert getattr(served, field) == getattr(local, field), field
    for secret in deploy_plan.SECRETS:
        assert getattr(served, secret.field) == getattr(local, secret.field), secret.field
    assert served.cors_origins == [WEB, "https://www.example.com"]
    assert served.scheduler_enabled is True
    for field in deploy_plan.DEFAULTS_ONLY:
        assert getattr(served, field) == Settings.model_fields[field].default, field


def test_secrets_stay_out_of_the_env_file() -> None:
    plan = deploy_plan.build_plan(full_settings(vapid_subject='mailto:"q"\\x@example.com'), (WEB,))
    text = deploy_plan.env_file_text(plan.env)
    assert leaked(text) == []
    assert text.isascii()
    parsed = {}
    for line in text.splitlines():
        key, _, value = line.partition(": ")
        parsed[key] = json.loads(value)  # 값마다 JSON 문자열(= YAML 문자열)
    assert parsed == plan.env
    assert parsed["VAPID_SUBJECT"] == 'mailto:"q"\\x@example.com'
    assert json.loads(parsed["CORS_ORIGINS"]) == [WEB]
    assert parsed["SCHEDULER_ENABLED"] == "true"


def test_empty_optional_values_are_not_sent() -> None:
    plan = deploy_plan.build_plan(
        full_settings(youth_api_key="", google_oauth_client_id="", vapid_subject=""), (WEB,)
    )
    assert "YOUTH_API_KEY" not in deploy_plan.secrets_flag(plan)
    assert "GOOGLE_OAUTH_CLIENT_ID" not in plan.env
    assert "VAPID_SUBJECT" not in plan.env
    assert "SUPABASE_JWT_SECRET" not in deploy_plan.secrets_flag(plan)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ([WEB], (WEB,)),
        ([WEB + "/"], (WEB,)),  # 끝의 /는 뗀다(CORS는 글자 그대로 비교한다)
        (["  HTTPS://UniPivot-Demo.Vercel.App/ "], (WEB,)),
        ([WEB, WEB + "/"], (WEB,)),
        ([WEB, "https://demo.example.com:8443"], (WEB, "https://demo.example.com:8443")),
    ],
)
def test_web_origins_are_normalized(raw: list[str], expected: tuple[str, ...]) -> None:
    origins, problems = deploy_plan.normalize_origins(raw)
    assert problems == []
    assert origins == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://unipivot-demo.vercel.app",
        "https://unipivot-demo.vercel.app/login",
        "https://unipivot-demo.vercel.app?x=1",
        "https://*.vercel.app",
        "https://user@unipivot-demo.vercel.app",
        "unipivot-demo.vercel.app",
        "",
    ],
)
def test_bad_web_origins_are_refused(raw: str) -> None:
    origins, problems = deploy_plan.normalize_origins([raw])
    assert origins == ()
    assert len(problems) == 1


def test_a_web_origin_is_required() -> None:
    assert deploy_plan.normalize_origins([])[1]


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        (POOLER_DB, True),
        (POOLER_DB.replace(":5432", ":6543"), True),  # 트랜잭션 풀러도 된다(prepare_threshold=None)
        ("host=aws-1-ap-northeast-2.pooler.supabase.com port=5432 dbname=postgres", True),
        ("", False),
        ("postgresql://postgres@127.0.0.1:5432/postgres", False),
        ("postgresql://postgres@localhost/postgres", False),
        ("postgresql:///postgres", False),  # 유닉스 소켓
        ("host=/var/run/postgresql dbname=postgres", False),
        ("postgresql://postgres:pw@db.abcdefghijklmnopqrst.supabase.co:5432/postgres", False),
        ("not a url at all ===", False),
    ],
)
def test_database_url_must_reach_supabase_from_cloud_run(url: str, ok: bool) -> None:
    problem = deploy_plan.database_problem(url)
    assert (problem is None) is ok
    if problem:
        assert "Pw-for-tests" not in problem and "pw@" not in problem


def test_good_settings_have_no_problems() -> None:
    assert deploy_plan.problems(full_settings()) == []


@pytest.mark.parametrize(
    ("overrides", "word"),
    [
        ({"google_cloud_project": ""}, "GOOGLE_CLOUD_PROJECT"),
        ({"google_cloud_project": "My Project"}, "GOOGLE_CLOUD_PROJECT"),
        ({"token_encryption_key": ""}, "TOKEN_ENCRYPTION_KEY"),
        ({"token_encryption_key": "not-a-fernet-key"}, "TOKEN_ENCRYPTION_KEY"),
        ({"supabase_secret_key": "sb_publishable_" + "a" * 30}, "publishable"),
        ({"supabase_url": SUPABASE + "/rest/v1"}, "SUPABASE_URL"),
        ({"database_url": "postgresql://postgres@127.0.0.1/postgres"}, "DATABASE_URL"),
    ],
)
def test_problems_block_the_deploy(overrides: dict[str, object], word: str) -> None:
    found = deploy_plan.problems(full_settings(**overrides))
    assert any(word in problem for problem in found), found


def test_checks_use_what_the_server_will_have() -> None:
    """로컬은 가짜 저장소로 돌아도 서버는 SUPABASE_URL의 저장소를 쓴다 — 서버가 가질 값으로 검사한다.

    레거시 JWT 비밀키가 있으면 로그인 확인은 주소를 보지 않아서, 저장소 검사만 이 차이를 잡는다."""
    local = full_settings(
        supabase_url="",
        supabase_jwt_secret="legacy-jwt-secret-for-tests",
        supabase_storage_base="http://127.0.0.1:54400/storage/v1",
    )
    found = deploy_plan.problems(local)
    assert any("SUPABASE_SECRET_KEY·SUPABASE_URL" in problem for problem in found), found


def test_warnings_name_what_will_be_missing() -> None:
    assert deploy_plan.warnings(full_settings()) == []
    found = deploy_plan.warnings(
        full_settings(
            scheduler_enabled=True,
            youth_api_key="",
            vapid_subject="",
            google_oauth_client_secret="",
        )
    )
    joined = "\n".join(found)
    for word in ("SCHEDULER_ENABLED", "YOUTH_API_KEY", "VAPID", "GOOGLE_OAUTH"):
        assert word in joined


def test_deploy_args_keep_one_instance_with_cpu() -> None:
    plan = deploy_plan.build_plan(full_settings(), (WEB,))
    args = deploy_plan.deploy_args(plan, "/tmp/env.yaml")
    assert args[:3] == ["run", "deploy", "unipivot-api"]
    for flag in (
        f"--project={PROJECT}",
        "--region=asia-northeast3",
        "--source=.",
        f"--service-account=unipivot-api@{PROJECT}.iam.gserviceaccount.com",
        "--cpu=1",
        "--memory=1Gi",
        "--no-cpu-throttling",
        "--max-instances=1",
        "--allow-unauthenticated",
        "--env-vars-file=/tmp/env.yaml",
        "--quiet",
    ):
        assert flag in args
    assert not any(arg.startswith("--min-instances") for arg in args)  # 지금 값을 둔다
    secrets = next(arg for arg in args if arg.startswith("--set-secrets="))
    assert "DATABASE_URL=unipivot-database-url:latest" in secrets
    assert "SUPABASE_SECRET_KEY=unipivot-supabase-secret-key:latest" in secrets
    assert leaked(" ".join(args)) == []


@pytest.mark.parametrize("count", [0, 1])
def test_min_instances_only_when_asked(count: int) -> None:
    plan = deploy_plan.build_plan(full_settings(), (WEB,), min_instances=count)
    assert f"--min-instances={count}" in deploy_plan.deploy_args(plan, "env.yaml")


# --- 비밀값 맞추기 ----------------------------------------------------------------------------------


def secret_plan() -> deploy_plan.Plan:
    return deploy_plan.build_plan(full_settings(), (WEB,))


def test_a_missing_secret_is_created_from_stdin() -> None:
    def answer(call: list[str], _: bytes | None) -> Result:
        return not_found() if call[:2] == ["secrets", "describe"] else Result(0)

    fake = FakeGcloud(answer)
    lines: list[str] = []
    cloudrun.sync_secrets(fake, secret_plan(), lines.append)

    created = fake.find("secrets", "create")
    assert len(created) == len(secret_plan().secrets)
    by_id = {call[2]: data for call, data, _ in created}
    assert by_id["unipivot-database-url"] == POOLER_DB.encode()  # 줄바꿈 없이 그대로
    for call, _, _ in fake.calls:
        assert leaked(" ".join(call)) == []  # 명령줄에는 값이 없다
    assert leaked("\n".join(lines)) == []
    assert any(f"({len(POOLER_DB)}자)" in line for line in lines)


def test_the_same_value_is_left_alone() -> None:
    values = {secret.secret_id: value.encode() for secret, value in secret_plan().secrets}

    def answer(call: list[str], _: bytes | None) -> Result:
        if call[:3] == ["secrets", "versions", "access"]:
            secret_id = call[4].removeprefix("--secret=")
            return Result(0, values[secret_id])
        return Result(0)

    fake = FakeGcloud(answer)
    cloudrun.sync_secrets(fake, secret_plan(), lambda _: None)
    assert fake.find("secrets", "versions", "add") == []
    assert fake.find("secrets", "create") == []


def test_a_changed_value_gets_a_new_version() -> None:
    def answer(call: list[str], _: bytes | None) -> Result:
        if call[:3] == ["secrets", "versions", "access"]:
            return Result(0, b"old-value")
        return Result(0)

    fake = FakeGcloud(answer)
    cloudrun.sync_secrets(fake, secret_plan(), lambda _: None)
    added = {call[3]: data for call, data, _ in fake.find("secrets", "versions", "add")}
    assert added["unipivot-supabase-secret-key"] == STORAGE_KEY.encode()


def test_a_secret_without_an_enabled_version_gets_one() -> None:
    def answer(call: list[str], _: bytes | None) -> Result:
        if call[:3] == ["secrets", "versions", "access"]:
            return Result(
                1, stderr=b"ERROR: FAILED_PRECONDITION: Secret Version is in DISABLED state."
            )
        return Result(0)

    fake = FakeGcloud(answer)
    cloudrun.sync_secrets(fake, secret_plan(), lambda _: None)
    assert len(fake.find("secrets", "versions", "add")) == len(secret_plan().secrets)


def test_a_permission_error_stops_without_creating() -> None:
    def answer(call: list[str], _: bytes | None) -> Result:
        return Result(1, stderr=b"ERROR: PERMISSION_DENIED: Permission denied on resource project.")

    fake = FakeGcloud(answer)
    with pytest.raises(DeployError, match="PERMISSION_DENIED"):
        cloudrun.sync_secrets(fake, secret_plan(), lambda _: None)
    assert fake.find("secrets", "create") == []


# --- 배포 명령 ----------------------------------------------------------------------------------


def test_deploy_end_to_end(workdir: Path) -> None:
    seen_env: dict[str, str] = {}

    def answer(call: list[str], _: bytes | None) -> Result:
        if call[:2] == ["run", "deploy"]:
            path = Path(
                next(arg for arg in call if arg.startswith("--env-vars-file=")).split("=", 1)[1]
            )
            seen_env["path"] = str(path)
            seen_env["text"] = path.read_text(encoding="utf-8")
            return Result(0)
        if call[:2] == ["secrets", "describe"]:
            return not_found()
        return described_url(call) or Result(0)

    fake = FakeGcloud(answer)
    code, lines = run_main(
        ["deploy", "--web-origin", WEB + "/", "--min-instances", "1"],
        settings=full_settings(api_prefix="/local-only"),  # 서버는 기본 경로를 쓴다
        runner=fake,
        workdir=workdir,
    )

    assert code == 0, lines
    deploy_call = fake.find("run", "deploy")[0]
    assert deploy_call[2] is False  # gcloud 진행을 그대로 보여 준다
    assert "--min-instances=1" in deploy_call[0]
    assert '"[\\"https://unipivot-demo.vercel.app\\"]"' in seen_env["text"]
    assert not Path(seen_env["path"]).exists()  # 끝나면 지운다
    assert f"Vercel의 NEXT_PUBLIC_API_BASE_URL: {URL}/api/v1" in lines
    output = "\n".join(lines) + "\n".join(" ".join(call) for call in fake.commands())
    assert leaked(output) == []
    # 순서: 비밀값 → 배포 → 주소
    order = [call[:2] for call in fake.commands()]
    assert order.index(["secrets", "create"]) < order.index(["run", "deploy"])
    assert order.index(["run", "deploy"]) < order.index(["run", "services"])


def test_a_failed_deploy_still_removes_the_env_file(workdir: Path) -> None:
    seen: list[Path] = []

    def answer(call: list[str], _: bytes | None) -> Result:
        if call[:2] == ["run", "deploy"]:
            seen.append(
                Path(next(a for a in call if a.startswith("--env-vars-file=")).split("=", 1)[1])
            )
            return Result(1)
        return Result(0, b"same") if call[:3] == ["secrets", "versions", "access"] else Result(0)

    code, lines = run_main(
        ["deploy", "--web-origin", WEB],
        settings=full_settings(),
        runner=FakeGcloud(answer),
        workdir=workdir,
    )
    assert code == 1
    assert any("gcloud run deploy가 실패" in line for line in lines)
    assert seen and not seen[0].exists()


def test_bad_settings_stop_before_gcloud(workdir: Path) -> None:
    fake = FakeGcloud()
    code, lines = run_main(
        ["deploy", "--web-origin", "http://unipivot-demo.vercel.app"],
        settings=full_settings(database_url="postgresql://postgres@127.0.0.1/postgres"),
        runner=fake,
        workdir=workdir,
    )
    assert code == 2
    assert fake.calls == []
    assert any("DATABASE_URL" in line for line in lines)
    assert any("웹 주소" in line for line in lines)


def test_dry_run_changes_nothing(workdir: Path) -> None:
    fake = FakeGcloud(refuse)
    code, lines = run_main(
        ["deploy", "--web-origin", WEB, "--dry-run"],
        settings=full_settings(lms_api_base="http://127.0.0.1:9999"),
        runner=fake,
        workdir=workdir,
    )
    assert code == 0, lines
    assert fake.calls == []
    text = "\n".join(lines)
    assert "(바꾸지 않음) gcloud run deploy unipivot-api" in text
    assert "LMS_API_BASE" in text  # 기본값을 쓰는 시험용 설정을 알린다
    assert f"DATABASE_URL({len(POOLER_DB)}자)" in text
    assert leaked(text) == []


def test_not_logged_in_stops(workdir: Path) -> None:
    fake = FakeGcloud(logged_in=False)
    code, lines = run_main(
        ["deploy", "--web-origin", WEB], settings=full_settings(), runner=fake, workdir=workdir
    )
    assert code == 1
    assert any("gcloud auth login" in line for line in lines)
    assert fake.calls == []


@pytest.mark.parametrize(
    "missing", [".gcloudignore", ".dockerignore", "Dockerfile", ".python-version"]
)
def test_runs_only_from_the_api_folder(workdir: Path, missing: str) -> None:
    (workdir / missing).unlink()
    code, lines = run_main(
        ["deploy", "--web-origin", WEB, "--dry-run"], settings=full_settings(), workdir=workdir
    )
    assert code == 1
    assert any(missing in line for line in lines)


@pytest.mark.parametrize("name", [".gcloudignore", ".dockerignore"])
def test_ignore_files_must_keep_env_out(workdir: Path, name: str) -> None:
    (workdir / name).write_text(".venv\n.env.local\n", encoding="utf-8")
    code, lines = run_main(
        ["deploy", "--web-origin", WEB, "--dry-run"], settings=full_settings(), workdir=workdir
    )
    assert code == 1
    assert any(name in line and ".env" in line for line in lines)


def test_the_real_api_folder_passes_the_checks() -> None:
    """레포의 Dockerfile·무시 목록이 배포 명령의 확인을 지난다."""
    cloudrun.check_workdir(API_DIR)


def test_the_upload_list_is_an_allow_list_that_covers_what_the_dockerfile_copies() -> None:
    """api 폴더에 놓인 다른 파일(키·저장한 응답)이 Cloud Build로 올라가지 않는다."""
    lines = [
        line.strip()
        for line in (API_DIR / ".gcloudignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert "/*" in lines
    allowed = {line[2:] for line in lines if line.startswith("!/")}
    dockerfile = (API_DIR / "Dockerfile").read_text(encoding="utf-8")
    copied = [
        part.rstrip("/")
        for line in dockerfile.splitlines()
        if line.startswith("COPY ") and "--from" not in line
        for part in line.split()[1:-1]
        if not part.startswith("--")
    ]
    assert copied
    for name in copied:
        assert name.rstrip("/") in {item.rstrip("/") for item in allowed}, name
    assert ".dockerignore" in allowed  # gcloud가 Dockerfile 옆의 .dockerignore를 쓴다


def test_gcloud_runs_without_logging_http_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    """비밀값이 gcloud 로그에 남지 않게 HTTP 로그를 끈다."""
    seen: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> object:
        seen.update(kwargs)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(cloudrun.shutil, "which", lambda _: "/bin/gcloud")
    monkeypatch.setattr(cloudrun.subprocess, "run", fake_run)
    monkeypatch.setenv("CLOUDSDK_CORE_LOG_HTTP", "true")
    monkeypatch.setenv("CLOUDSDK_CORE_VERBOSITY", "debug")
    cloudrun.gcloud_runner()(["auth", "list"])
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["CLOUDSDK_CORE_LOG_HTTP"] == "false"
    assert env["CLOUDSDK_CORE_VERBOSITY"] == "warning"


def test_the_image_runs_one_worker_on_the_given_port() -> None:
    dockerfile = (API_DIR / "Dockerfile").read_text(encoding="utf-8")
    command = next(line for line in dockerfile.splitlines() if line.startswith("CMD"))
    assert '--port \\"${PORT:-8080}\\"' in command
    assert "--workers" not in command  # 스케줄러가 한 번만 돈다
    assert "--forwarded-allow-ips '*'" in command
    assert "uv sync --locked --no-dev" in dockerfile
    assert "USER " in dockerfile


# --- 처음 설정 ----------------------------------------------------------------------------------


def setup_answer(
    *, account_exists: bool, flaky_binding: int = 0
) -> Callable[[list[str], bytes | None], Result]:
    remaining = {"flaky": flaky_binding}

    def answer(call: list[str], _: bytes | None) -> Result:
        if call[:3] == ["iam", "service-accounts", "describe"]:
            return Result(0) if account_exists else not_found("Unknown service account")
        if call[:2] == ["projects", "describe"]:
            return Result(0, json.dumps({"projectNumber": "987654321"}).encode())
        if call[:2] == ["projects", "add-iam-policy-binding"] and remaining["flaky"]:
            remaining["flaky"] -= 1
            return Result(
                1, stderr=b"ERROR: INVALID_ARGUMENT: Service account unipivot-api does not exist."
            )
        return Result(0)

    return answer


def test_setup_creates_the_account_and_grants_roles() -> None:
    fake = FakeGcloud(setup_answer(account_exists=False))
    code, lines = run_main(["setup"], settings=full_settings(), runner=fake)
    assert code == 0, lines
    enabled = fake.find("services", "enable")[0][0]
    for api in ("run.googleapis.com", "aiplatform.googleapis.com", "secretmanager.googleapis.com"):
        assert api in enabled
    assert fake.find("iam", "service-accounts", "create")
    bindings = [
        (call[3], call[4]) for call, _, _ in fake.find("projects", "add-iam-policy-binding")
    ]
    account = f"--member=serviceAccount:unipivot-api@{PROJECT}.iam.gserviceaccount.com"
    assert (account, "--role=roles/aiplatform.user") in bindings
    assert (account, "--role=roles/secretmanager.secretAccessor") in bindings
    assert (
        "--member=serviceAccount:987654321-compute@developer.gserviceaccount.com",
        "--role=roles/run.builder",
    ) in bindings


def test_setup_twice_does_not_recreate() -> None:
    fake = FakeGcloud(setup_answer(account_exists=True))
    assert run_main(["setup"], settings=full_settings(), runner=fake)[0] == 0
    assert fake.find("iam", "service-accounts", "create") == []


def test_setup_waits_for_a_new_account_to_appear() -> None:
    fake = FakeGcloud(setup_answer(account_exists=False, flaky_binding=2))
    waits: list[float] = []
    lines: list[str] = []
    code = cloudrun.main(
        ["setup"], settings=full_settings(), runner=fake, out=lines.append, sleep=waits.append
    )
    assert code == 0, lines
    assert waits == [5.0, 5.0]


def test_setup_dry_run_changes_nothing() -> None:
    fake = FakeGcloud(refuse)
    code, lines = run_main(["setup", "--dry-run"], settings=full_settings(), runner=fake)
    assert code == 0
    assert fake.calls == []
    assert any("roles/aiplatform.user" in line for line in lines)


def test_setup_needs_a_project() -> None:
    code, lines = run_main(
        ["setup"], settings=full_settings(google_cloud_project=""), runner=FakeGcloud()
    )
    assert code == 1
    assert any("GOOGLE_CLOUD_PROJECT" in line for line in lines)


# --- gcloud 부르기 -------------------------------------------------------------------------------


def test_gcloud_must_be_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cloudrun.shutil, "which", lambda _: None)
    with pytest.raises(DeployError, match="Google Cloud CLI"):
        cloudrun.gcloud_runner()


def test_gcloud_gets_values_on_stdin_and_never_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, object]] = []

    class Done:
        returncode = 0
        stdout = b"out"
        stderr = b""

    def fake_run(command: list[str], **kwargs: object) -> Done:
        seen.append({"command": command, **kwargs})
        return Done()

    monkeypatch.setattr(cloudrun.shutil, "which", lambda _: "/opt/sdk/bin/gcloud")
    monkeypatch.setattr(cloudrun.subprocess, "run", fake_run)
    run = cloudrun.gcloud_runner()

    assert run(["secrets", "create", "x"], input=b"value") == Result(0, b"out", b"")
    run(["run", "deploy"], capture=False)

    first, second = seen
    assert first["command"] == ["/opt/sdk/bin/gcloud", "secrets", "create", "x"]
    assert first["input"] == b"value" and "stdin" not in first
    assert second["stdin"] is cloudrun.subprocess.DEVNULL  # 묻는 창이 떠도 기다리지 않는다
    assert second["capture_output"] is False
    env = first["env"]
    assert isinstance(env, dict) and env["CLOUDSDK_CORE_DISABLE_PROMPTS"] == "1"
