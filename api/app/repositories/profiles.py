"""profiles·oauth_tokens·lms_connections·notifications 조회 (ERD v0.9). 판정 결과는 opportunities.py."""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from psycopg import AsyncConnection, sql

from app.db import get_conn
from app.schemas.me import (
    COMPLETION_FIELDS,
    PROFILE_FIELDS,
    ConsentResult,
    IncomeConsentResult,
    LmsSummary,
    Me,
    Profile,
    ProfileCompletion,
)

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"

# 선택 동의를 하면 시각을 남기고(이미 있으면 유지), 철회하면 시각과 소득·수급 값을 한 번에 지운다.
# 한 문장으로 바꿔야 DB 제약(profiles_income_consent_chk)을 지키며 철회할 수 있다
_INCOME_CONSENT_SET = (
    "income_info_agreed_at = case when %(agree)s then coalesce(income_info_agreed_at, now()) end,"
    " income_bracket = case when %(agree)s then income_bracket end,"
    " median_income_pct = case when %(agree)s then median_income_pct end,"
    " welfare_status = case when %(agree)s then welfare_status end"
)


@dataclass(frozen=True)
class Consents:
    terms_privacy: bool  # 이용약관·개인정보 (필수)
    income_info: bool  # 소득·수급 정보 (선택)


class ProfileRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def lock(self, user_id: str) -> None:
        """요청이 끝날 때까지 프로필 행을 잠근다. 읽고 비교해 저장하는 사이에 같은 사용자의 다른 요청이
        끼지 않는다. no key update라서 이 사용자의 다른 행이 profiles를 참조하며 넣는 것은 막지 않는다."""
        await self.conn.execute(
            "select 1 from profiles where id = %s for no key update", (user_id,)
        )

    async def ensure(self, user_id: str, display_name: str | None) -> None:
        """로그인 직후 profiles 행을 만든다. 이미 있으면 비어 있는 이름만 채운다."""
        await self.conn.execute(
            "insert into profiles (id, display_name) values (%s, %s) on conflict (id)"
            " do update set display_name = coalesce(profiles.display_name, excluded.display_name)",
            (user_id, display_name),
        )

    async def get_me(self, user_id: str) -> Me | None:
        filled = sql.SQL(" + ").join(
            sql.SQL("(p.{} is not null)::int").format(sql.Identifier(f)) for f in COMPLETION_FIELDS
        )
        query = sql.SQL(
            """
            select p.id, p.display_name, p.hyin_verified_at,
                   p.terms_agreed_at is not null and p.privacy_agreed_at is not null as consented,
                   p.income_info_agreed_at is not null as income_info_consented,
                   {filled} as filled,
                   exists(select 1 from oauth_tokens t where t.user_id = p.id
                          and t.provider = 'google' and t.refresh_token is not null)
                       as calendar_connected,
                   l.status as lms_status, l.last_synced_at as lms_last_synced_at,
                   (select count(*) from notifications n where n.user_id = p.id
                    and n.read_at is null and n.scheduled_at <= now()) as unread
            from profiles p left join lms_connections l on l.user_id = p.id
            where p.id = %s
            """
        ).format(filled=filled)
        row = await (await self.conn.execute(query, (user_id,))).fetchone()
        if row is None:
            return None
        lms = None
        if row["lms_status"]:
            lms = LmsSummary(status=row["lms_status"], last_synced_at=row["lms_last_synced_at"])
        return Me(
            user_id=str(row["id"]),
            display_name=row["display_name"] or "학생",
            hyin_verified=row["hyin_verified_at"] is not None,
            calendar_connected=row["calendar_connected"],
            lms=lms,
            profile_completion=ProfileCompletion(
                filled=row["filled"], total=len(COMPLETION_FIELDS)
            ),
            consented=row["consented"],
            income_info_consented=row["income_info_consented"],
            unread_notifications=row["unread"],
        )

    async def get_profile(self, user_id: str) -> Profile | None:
        query = sql.SQL("select {} from profiles where id = %s").format(
            sql.SQL(", ").join(map(sql.Identifier, PROFILE_FIELDS))
        )
        row = await (await self.conn.execute(query, (user_id,))).fetchone()
        return Profile.model_validate(row) if row else None

    async def update_profile(self, user_id: str, values: dict[str, Any]) -> None:
        if not values:
            return
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(key), sql.Placeholder(key)) for key in values
        )
        query = sql.SQL("update profiles set {}, profile_updated_at = now() where id = %(id)s")
        await self.conn.execute(query.format(assignments), {**values, "id": user_id})

    async def get_consents(self, user_id: str) -> Consents:
        row = await (
            await self.conn.execute(
                "select terms_agreed_at is not null and privacy_agreed_at is not null as terms,"
                " income_info_agreed_at is not null as income from profiles where id = %s",
                (user_id,),
            )
        ).fetchone()
        if row is None:
            return Consents(terms_privacy=False, income_info=False)
        return Consents(terms_privacy=row["terms"], income_info=row["income"])

    async def save_consent(
        self, user_id: str, version: str, agree_income_info: bool
    ) -> ConsentResult:
        row = await (
            await self.conn.execute(
                "update profiles set terms_agreed_at = now(), privacy_agreed_at = now(),"
                f" consent_version = %(version)s, {_INCOME_CONSENT_SET} where id = %(id)s"
                " returning terms_agreed_at, privacy_agreed_at, income_info_agreed_at,"
                " consent_version",
                {"version": version, "agree": agree_income_info, "id": user_id},
            )
        ).fetchone()
        return ConsentResult.model_validate(row)

    async def set_income_consent(self, user_id: str, agree: bool) -> IncomeConsentResult:
        row = await (
            await self.conn.execute(
                f"update profiles set {_INCOME_CONSENT_SET},"
                " profile_updated_at = case when %(agree)s then profile_updated_at else now() end"
                " where id = %(id)s returning income_info_agreed_at",
                {"agree": agree, "id": user_id},
            )
        ).fetchone()
        return IncomeConsentResult.model_validate(row)

    async def save_google_tokens(self, user_id: str, access_token: str, refresh_token: str) -> None:
        """토큰은 암호화된 값만 받는다. access token 만료는 Google 기본값(1시간)보다 조금 짧게 잡는다."""
        await self.conn.execute(
            "insert into oauth_tokens (user_id, provider, access_token, refresh_token, scope,"
            " expires_at) values (%s, 'google', %s, %s, %s, now() + interval '55 minutes')"
            " on conflict (user_id, provider) do update set access_token = excluded.access_token,"
            " refresh_token = excluded.refresh_token, scope = excluded.scope,"
            " expires_at = excluded.expires_at",
            (user_id, access_token, refresh_token, CALENDAR_SCOPE),
        )


def get_profile_repo(conn: Annotated[AsyncConnection, Depends(get_conn)]) -> ProfileRepository:
    return ProfileRepository(conn)


ProfileRepoDep = Annotated[ProfileRepository, Depends(get_profile_repo)]
