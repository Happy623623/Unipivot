"""Cloud Run에 api를 올린다(docs/배포_절차.md). **api 폴더에서** 돌린다.

    uv run python -m app.deploy.cloudrun setup                       # 처음 한 번: API·서비스 계정·권한
    uv run python -m app.deploy.cloudrun deploy --web-origin https://<웹 주소> [--min-instances 0|1]

둘 다 `--dry-run`을 붙이면 아무것도 바꾸지 않고 할 일만 찍는다. 설정은 `api/.env`에서 읽고(서버와 같은
방식), 비밀값은 Secret Manager로 보낸다. **값은 화면에 찍지 않는다**(이름과 길이만). gcloud에는 비밀값을
명령줄이 아니라 표준 입력으로 넘긴다 — 명령줄은 다른 프로그램과 셸 기록에 남는다.

gcloud는 `gcloud auth login`으로 로그인해 둔다(로컬 Gemini용 `application-default login`과 다르다).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.deploy import plan as deploy_plan
from app.deploy.plan import Plan
from app.runtime import utf8_output

# 배포에 올리는 폴더에 있어야 하는 것. 무시 목록 두 개가 없으면 .env가 Cloud Build로 같이 올라갈 수 있다
_REQUIRED_FILES = (
    "Dockerfile",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".dockerignore",
    ".gcloudignore",
)
_IGNORE_FILES = (".dockerignore", ".gcloudignore")
_BINDING_RETRIES = 6  # 새로 만든 서비스 계정이 IAM에 보이기까지 잠깐 걸린다
_BINDING_WAIT_SECONDS = 5.0


def _say(text: str) -> None:
    """gcloud 진행 출력과 순서가 섞이지 않게 바로 내보낸다."""
    print(text, flush=True)


class DeployError(Exception):
    """사람이 고쳐야 멈추는 실패. 문구는 무엇을 하면 되는지 쓴다."""


@dataclass(frozen=True)
class Result:
    code: int
    stdout: bytes = b""
    stderr: bytes = b""

    def error_text(self) -> str:
        """gcloud 오류의 마지막 몇 줄. gcloud 오류에는 비밀값이 들어가지 않는다(값은 표준 입력으로만 준다)."""
        lines = [
            line for line in self.stderr.decode("utf-8", "replace").splitlines() if line.strip()
        ]
        return "\n".join(lines[-4:]) or f"(gcloud 종료 코드 {self.code})"


class Runner(Protocol):
    def __call__(
        self, args: Sequence[str], *, input: bytes | None = None, capture: bool = True
    ) -> Result: ...


def gcloud_runner() -> Runner:
    """gcloud를 부른다. Windows에서는 gcloud.cmd를 찾는다. 묻는 창이 뜨지 않게 한다."""
    path = shutil.which("gcloud")
    if path is None:
        raise DeployError(
            "gcloud를 찾지 못했어요. Google Cloud CLI를 설치하고 PowerShell을 새로 연 뒤 다시 해 주세요"
        )
    # gcloud가 HTTP 본문(비밀값 포함)을 로그에 남기지 않게 한다
    env = {
        **os.environ,
        "CLOUDSDK_CORE_DISABLE_PROMPTS": "1",
        "CLOUDSDK_CORE_LOG_HTTP": "false",
        "CLOUDSDK_CORE_VERBOSITY": "warning",
    }

    def run(args: Sequence[str], *, input: bytes | None = None, capture: bool = True) -> Result:
        stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        done = subprocess.run([path, *args], capture_output=capture, check=False, env=env, **stdin)
        return Result(done.returncode, done.stdout or b"", done.stderr or b"")

    return run


def _missing(result: Result) -> bool:
    """없어서 실패했는가(권한·네트워크 실패와 가른다)."""
    return b"NOT_FOUND" in result.stderr or b"FAILED_PRECONDITION" in result.stderr


def _must(result: Result, what: str) -> Result:
    if result.code != 0:
        raise DeployError(f"{what}에 실패했어요:\n{result.error_text()}")
    return result


def check_login(run: Runner) -> None:
    done = _must(run(["auth", "list", "--format=json"]), "gcloud 로그인 확인")
    try:
        accounts = json.loads(done.stdout or b"[]")
    except ValueError:
        accounts = []
    if not any(item.get("status") == "ACTIVE" for item in accounts if isinstance(item, dict)):
        raise DeployError("gcloud에 로그인돼 있지 않아요. gcloud auth login을 먼저 해 주세요")


def check_workdir(workdir: Path) -> None:
    missing = [name for name in _REQUIRED_FILES if not (workdir / name).is_file()]
    if missing or not (workdir / "app").is_dir():
        raise DeployError(
            f"api 폴더에서 돌려 주세요(없는 것: {', '.join(missing) or 'app/'}). "
            "cd api 뒤에 다시 해요"
        )
    for name in _IGNORE_FILES:
        lines = {line.strip() for line in (workdir / name).read_text(encoding="utf-8").splitlines()}
        if ".env" not in lines:
            raise DeployError(
                f"{name}에 .env 줄이 없어요. 그대로 올리면 비밀값 파일이 같이 올라가요"
            )


def sync_secrets(run: Runner, plan: Plan, out: Callable[[str], None]) -> None:
    """비밀값을 Secret Manager에 맞춘다. 같으면 그대로 두고, 다르면 새 버전을 더한다."""
    project = f"--project={plan.project}"
    for secret, value in plan.secrets:
        data = value.encode("utf-8")
        label = f"  {secret.env} → {secret.secret_id}"
        found = run(["secrets", "describe", secret.secret_id, project, "--format=json"])
        if found.code != 0:
            if not _missing(found):
                raise DeployError(f"{secret.secret_id}를 확인하지 못했어요:\n{found.error_text()}")
            _must(
                run(
                    [
                        "secrets",
                        "create",
                        secret.secret_id,
                        project,
                        "--replication-policy=automatic",
                        "--data-file=-",
                    ],
                    input=data,
                ),
                f"{secret.secret_id} 만들기",
            )
            out(f"{label}: 새로 만들었어요({len(value)}자)")
            continue
        latest = run(
            ["secrets", "versions", "access", "latest", f"--secret={secret.secret_id}", project]
        )
        if latest.code == 0 and latest.stdout == data:
            out(f"{label}: 그대로예요({len(value)}자)")
            continue
        if latest.code != 0 and not _missing(latest):
            raise DeployError(f"{secret.secret_id}의 값을 읽지 못했어요:\n{latest.error_text()}")
        _must(
            run(
                ["secrets", "versions", "add", secret.secret_id, project, "--data-file=-"],
                input=data,
            ),
            f"{secret.secret_id} 새 버전",
        )
        out(f"{label}: 새 값으로 바꿨어요({len(value)}자)")


def service_url(run: Runner, plan: Plan) -> str:
    done = _must(
        run(
            [
                "run",
                "services",
                "describe",
                plan.service,
                f"--project={plan.project}",
                f"--region={plan.region}",
                "--format=json",
            ]
        ),
        "서비스 주소 확인",
    )
    try:
        url = json.loads(done.stdout)["status"]["url"]
    except (ValueError, KeyError, TypeError):
        raise DeployError(
            "서비스 주소를 읽지 못했어요. Cloud Run 콘솔에서 주소를 확인하세요"
        ) from None
    return str(url)


def deploy(run: Runner, plan: Plan, out: Callable[[str], None]) -> str:
    """비밀값을 맞추고 소스를 올려 새 버전을 띄운다. 서비스 주소를 돌려준다."""
    check_login(run)
    out("비밀값(Secret Manager)")
    sync_secrets(run, plan, out)
    # 환경 변수 파일(비밀 아님)은 레포 밖 임시 폴더에 쓰고 끝나면 지운다
    with tempfile.TemporaryDirectory(prefix="unipivot-deploy-") as folder:
        env_file = Path(folder) / "env.yaml"
        env_file.write_text(deploy_plan.env_file_text(plan.env), encoding="utf-8")
        out("Cloud Run에 올려요(처음은 5~10분 걸려요. 아래는 gcloud가 찍는 진행이에요)")
        done = run(deploy_plan.deploy_args(plan, str(env_file)), capture=False)
    if done.code != 0:
        raise DeployError("gcloud run deploy가 실패했어요. 위에 gcloud가 찍은 오류를 보세요")
    return service_url(run, plan)


def _bind(
    run: Runner, project: str, member: str, role: str, sleep: Callable[[float], None]
) -> None:
    args = [
        "projects",
        "add-iam-policy-binding",
        project,
        f"--member={member}",
        f"--role={role}",
        "--condition=None",
        "--quiet",
    ]
    for attempt in range(_BINDING_RETRIES):
        done = run(args)
        if done.code == 0:
            return
        # 방금 만든 서비스 계정은 잠깐 "없다"고 나온다
        if b"does not exist" not in done.stderr or attempt == _BINDING_RETRIES - 1:
            raise DeployError(f"{role} 권한 주기에 실패했어요:\n{done.error_text()}")
        sleep(_BINDING_WAIT_SECONDS)


def setup(
    run: Runner,
    project: str,
    out: Callable[[str], None],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """처음 한 번: API 켜기, 서버용 서비스 계정과 권한, 소스 빌드 계정 권한. 다시 돌려도 된다."""
    check_login(run)
    out(f"API 켜기: {', '.join(deploy_plan.APIS)} (처음은 1~2분)")
    _must(run(["services", "enable", *deploy_plan.APIS, f"--project={project}"]), "API 켜기")
    account = deploy_plan.service_account(project)
    found = run(
        ["iam", "service-accounts", "describe", account, f"--project={project}", "--format=json"]
    )
    if found.code != 0:
        if not _missing(found):
            raise DeployError(f"서비스 계정을 확인하지 못했어요:\n{found.error_text()}")
        _must(
            run(
                [
                    "iam",
                    "service-accounts",
                    "create",
                    deploy_plan.SERVICE_ACCOUNT_ID,
                    f"--project={project}",
                    f"--display-name={deploy_plan.SERVICE_ACCOUNT_ID}",
                ]
            ),
            "서비스 계정 만들기",
        )
        out(f"서비스 계정을 만들었어요: {account}")
    else:
        out(f"서비스 계정이 있어요: {account}")
    for role in deploy_plan.SERVICE_ACCOUNT_ROLES:
        _bind(run, project, f"serviceAccount:{account}", role, sleep)
        out(f"  {role}")
    described = _must(run(["projects", "describe", project, "--format=json"]), "프로젝트 번호 확인")
    try:
        number = str(json.loads(described.stdout)["projectNumber"])
    except (ValueError, KeyError, TypeError):
        raise DeployError(
            "프로젝트 번호를 읽지 못했어요. 콘솔 홈의 프로젝트 번호를 확인하세요"
        ) from None
    builder = f"serviceAccount:{number}-compute@developer.gserviceaccount.com"
    _bind(run, project, builder, deploy_plan.BUILDER_ROLE, sleep)
    out(f"소스 빌드 계정({number}-compute@…)에 {deploy_plan.BUILDER_ROLE}")
    out("끝났어요. 권한이 퍼지는 데 1~2분 걸리니 잠깐 뒤에 deploy를 돌리세요")


def describe(plan: Plan, settings: Settings) -> list[str]:
    """--dry-run과 배포 전에 찍는 계획. 비밀값은 이름과 길이만."""
    lines = [
        f"프로젝트 {plan.project} · 지역 {plan.region} · 서비스 {plan.service}",
        f"서비스 계정 {plan.service_account}",
        f"웹 주소(CORS) {', '.join(plan.origins)}",
        "인스턴스 최대 1개 · CPU 늘 켬 · 최소 "
        + (
            "지금 값 그대로(처음이면 0)"
            if plan.min_instances is None
            else f"{plan.min_instances}개"
        ),
        "비밀값 " + ", ".join(f"{secret.env}({len(value)}자)" for secret, value in plan.secrets),
        "환경 변수 " + ", ".join(plan.env),
    ]
    if differ := deploy_plan.defaults_differ(settings):
        lines.append(f"로컬 값과 달라도 기본값을 쓰는 것 {', '.join(differ)}")
    return lines


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.deploy.cloudrun", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup_cmd = commands.add_parser("setup", help="처음 한 번: API·서비스 계정·권한")
    setup_cmd.add_argument("--dry-run", action="store_true", help="바꾸지 않고 할 일만 찍는다")
    deploy_cmd = commands.add_parser("deploy", help="비밀값을 맞추고 새 버전을 올린다")
    deploy_cmd.add_argument(
        "--web-origin",
        action="append",
        default=[],
        help="웹 주소(https://<프로젝트>.vercel.app). 여러 번 줄 수 있다",
    )
    deploy_cmd.add_argument(
        "--min-instances",
        type=int,
        choices=(0, 1),
        help="0: 쓸 때만 켠다(평소) · 1: 늘 켠다(데모 기간). 빼면 지금 값을 둔다",
    )
    deploy_cmd.add_argument("--region", default=deploy_plan.REGION)
    deploy_cmd.add_argument("--service", default=deploy_plan.SERVICE)
    deploy_cmd.add_argument("--dry-run", action="store_true", help="바꾸지 않고 할 일만 찍는다")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    runner: Runner | None = None,
    workdir: Path | None = None,
    out: Callable[[str], None] = _say,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = _parser().parse_args(argv)
    settings = settings or Settings()
    workdir = workdir or Path.cwd()
    try:
        if args.command == "setup":
            project = settings.google_cloud_project.strip()
            if problem := deploy_plan.project_problem(project):
                raise DeployError(problem)
            if args.dry_run:
                out(f"(바꾸지 않음) 프로젝트 {project}")
                out(f"켤 API {', '.join(deploy_plan.APIS)}")
                out(
                    f"서비스 계정 {deploy_plan.service_account(project)}: {', '.join(deploy_plan.SERVICE_ACCOUNT_ROLES)}"
                )
                out(f"소스 빌드 계정({{번호}}-compute@…): {deploy_plan.BUILDER_ROLE}")
                return 0
            setup(runner or gcloud_runner(), project, out, sleep=sleep)
            return 0
        check_workdir(workdir)
        origins, found = deploy_plan.normalize_origins(args.web_origin)
        found += deploy_plan.target_problems(args.region, args.service)
        found += deploy_plan.problems(settings)
        if found:
            out("배포하지 않았어요. 고칠 것:")
            for problem in found:
                out(f"  - {problem}")
            return 2
        plan = deploy_plan.build_plan(
            settings,
            origins,
            region=args.region,
            service=args.service,
            min_instances=args.min_instances,
        )
        for line in describe(plan, settings):
            out(line)
        for warning in deploy_plan.warnings(settings):
            out(f"알림: {warning}")
        if args.dry_run:
            command = deploy_plan.deploy_args(plan, "<임시 폴더>/env.yaml")
            out("(바꾸지 않음) gcloud " + " ".join(command))
            return 0
        url = deploy(runner or gcloud_runner(), plan, out)
    except DeployError as error:
        out(f"멈췄어요: {error}")
        return 1
    out(f"api 주소: {url}")
    out(f'확인: {url}/health 를 열면 {{"status":"ok"}}가 보여요')
    # 배포 서버는 API_PREFIX를 기본값으로 쓴다(plan.DEFAULTS_ONLY)
    out(f"Vercel의 NEXT_PUBLIC_API_BASE_URL: {url}{Settings.model_fields['api_prefix'].default}")
    return 0


if __name__ == "__main__":
    utf8_output()
    sys.exit(main())
