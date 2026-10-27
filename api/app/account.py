"""탈퇴 (API 명세 4장 `DELETE /me`, F-06). 한 번에 넷을 한다 — 파일, Google 권한, DB, 로그인 계정.

순서가 중요하다.
1. **저장소의 파일**을 먼저 지운다. 실패하면 502로 끝내고 아무것도 바꾸지 않는다 — 개인 파일을
   남긴 채 "탈퇴했어요"라고 할 수는 없다. 다시 누르면 처음부터 다시 한다.
   지우기 전에 저장소 설정을 본다. publishable key처럼 권한이 모자란 키로 지우면 저장소는 파일을
   못 보고 "없는 파일"(`NoSuchKey`)로 답하는데, 지우기는 그 답을 "이미 지웠다"로 받는다(다시 누를 때
   필요하다). 그대로 가면 파일은 저장소에 남고 기록만 사라진다. 그래서 설정에 고칠 점이 있으면 하나도
   지우지 않고 같은 502로 멈춘다(받기 주소가 그 404를 믿지 않는 것과 같은 기준)
   그다음 저장소의 **내 폴더(`<user_id>/`)를 훑어** 기록이 없는 파일도 지운다(올린 뒤 기록의 커밋이 정말
   실패해 남은 것 — 그런 파일은 기록이 없어 목록으로는 못 찾는다). 목록을 받지 못하면 같은 502로 멈춘다.
   저장소 설정이 없거나 틀리면(로컬) 훑지 않는다 — 기록된 파일이 있었으면 위에서 이미 멈췄다
2. **Google 캘린더 권한**을 거둔다(되는 만큼. 연결 해제와 같은 함수)
3. **profiles 행**을 지운다. 딸린 행(토큰·설정·알림·플래너·판정·파일 기록·구독)은 cascade로
   사라지고, 공유 포스터 공고의 업로더와 실행 로그의 사용자는 null이 된다(ERD 1장 설계 원칙)
   지우기 직전에 profiles 행을 잠그고(for update) 파일 목록을 **다시** 받아, 1 뒤에 들어온 파일(업로드·LMS
   첨부)도 지운다. 잠근 뒤로 파일 기록을 넣는 요청은 탈퇴가 끝날 때까지 기다렸다가 프로필이 없어 실패하고, 그쪽이
   방금 올린 파일을 지운다. 잠그지 않으면 목록을 받은 뒤 들어온 기록은 cascade로만 사라지고 파일은 저장소에 남는다.
   잠금은 이 마지막 단계에서만 쥔다 — 저장소·Google을 부르는 동안 쥐고 있으면 그 사용자의 다른 요청(LMS 동기화·
   준비하기)이 오래 기다리고, 딸린 행을 먼저 잠근 쪽과 교착이 생긴다(검토가 재현)
4. 지운 것을 **확정(커밋)**한 뒤 **Supabase 로그인 계정**(auth.users)을 관리자 API로 지운다(app/auth_admin.py).
   확정하기 전에 부르면 Supabase가 auth.users → profiles cascade를 하다 3에서 쥔 잠금을 기다리고, 이쪽은 그
   응답을 기다려 서로 막힌다. 지우지 못해도(로그인 서버에 닿지 못함, 키가 틀림, 설정이 없는 로컬) 탈퇴는
   끝낸다 — Google 권한 해제와 같다. 개인 데이터는 이미 지워 확정했고 되돌릴 수 없으니 "탈퇴하지 못했어요"라고
   할 수 없다. 이유는 경고 로그에 남긴다. 남은 계정에는 로그인 정보(이메일·이름·사진)만 있고, 그 계정으로 다시
   탈퇴를 누르면(프로필이 없어도) 이 단계를 다시 한다

Google 캘린더에 이미 넣은 일정은 지우지 않는다(명세 4장).
"""

import logging

from app.auth_admin import AuthAdminError, SupabaseAuthAdmin
from app.calendar.service import CalendarService
from app.config import Settings
from app.errors import ApiError
from app.repositories.files import FileRepository
from app.repositories.profiles import ProfileRepository
from app.uploads.storage import StorageError, SupabaseStorage, storage_settings_problem

logger = logging.getLogger(__name__)

STORAGE_FAILED = "파일을 지우지 못해 탈퇴를 멈췄어요. 잠시 후 다시 시도해 주세요."


async def delete_account(
    user_id: str,
    *,
    files: FileRepository,
    storage: SupabaseStorage,
    calendar: CalendarService,
    profiles: ProfileRepository,
    auth_admin: SupabaseAuthAdmin,
    settings: Settings,
) -> bool:
    """탈퇴. 지울 프로필이 있었으면 True다(없어도 204 — 두 번 눌러도 같다)."""
    paths = await files.storage_paths(user_id)
    await _remove_files(paths, storage, settings)
    removed = set(paths) | await _sweep_folder(user_id, set(paths), storage, settings)
    await calendar.disconnect(user_id)
    await profiles.lock_for_delete(user_id)
    await _remove_files(
        [path for path in await files.storage_paths(user_id) if path not in removed],
        storage,
        settings,
    )
    deleted = await profiles.delete(user_id)
    await profiles.commit()  # 잠금을 풀어야 로그인 계정 지우기의 cascade가 기다리지 않는다
    await _delete_login(user_id, auth_admin)
    return deleted


async def _delete_login(user_id: str, auth_admin: SupabaseAuthAdmin) -> None:
    """로그인 계정을 지운다(되는 만큼). 못 지우면 경고만 남긴다 — Google 권한 해제와 같다."""
    try:
        await auth_admin.delete_user(user_id)
    except AuthAdminError as exc:
        logger.warning("탈퇴: 로그인 계정은 지우지 못했어요(데이터는 지웠어요): %s", exc)


async def _sweep_folder(
    user_id: str, removed: set[str], storage: SupabaseStorage, settings: Settings
) -> set[str]:
    """저장소의 내 폴더에 남은 파일(기록이 없는 것)을 지운다. 지운 경로를 돌려준다."""
    if storage_settings_problem(settings):
        return set()
    try:
        left = [path for path in await storage.list_paths(user_id) if path not in removed]
    except StorageError as exc:
        logger.warning("탈퇴 중 내 폴더를 훑지 못했어요: %s", exc)
        raise ApiError(502, "STORAGE_API_ERROR", STORAGE_FAILED) from exc
    if left:
        logger.info("탈퇴: 기록이 없는 파일 %d개를 저장소에서 지워요", len(left))
    await _remove_files(left, storage, settings)
    return set(left)


async def _remove_files(paths: list[str], storage: SupabaseStorage, settings: Settings) -> None:
    """저장소에서 지운다. 하나라도 못 지우면 502로 멈춘다."""
    # 파일이 없으면 저장소를 부르지 않으니 설정도 보지 않는다(저장소 설정이 없는 로컬에서도 탈퇴된다)
    if paths and (problem := storage_settings_problem(settings)):
        logger.warning("파일을 지우기 전에 탈퇴를 멈췄어요. 저장소 설정 확인: %s", problem)
        raise ApiError(502, "STORAGE_API_ERROR", STORAGE_FAILED)
    for path in paths:
        try:
            await storage.remove(path)
        except StorageError as exc:
            logger.warning("탈퇴 중 파일을 지우지 못했어요: %s", exc)
            raise ApiError(502, "STORAGE_API_ERROR", STORAGE_FAILED) from exc
