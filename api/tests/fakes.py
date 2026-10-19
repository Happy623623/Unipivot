"""단위 테스트용 가짜 저장소. 실제 저장소와 메서드 이름·반환 타입을 맞춘다."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.repositories.opportunities import FeedPage, FeedQuery, Refresh
from app.repositories.profiles import Consents
from app.schemas.me import (
    COMPLETION_FIELDS,
    INCOME_FIELDS,
    ConsentResult,
    IncomeConsentResult,
    Me,
    Profile,
    ProfileCompletion,
    Settings,
)
from app.schemas.meta import Department
from app.schemas.metrics import (
    EligibilityMatrix,
    Latency,
    Metrics,
    ProductMetrics,
    Ratio,
    ScenarioMetrics,
    UndeterminedRate,
)
from app.schemas.opportunities import FeedCounts, OpportunityDetail, OpportunityItem


class FakeProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, str]] = {}
        self.settings: dict[str, Settings] = {}
        self.locks: list[str] = []

    async def lock(self, user_id: str) -> None:
        self.locks.append(user_id)

    async def ensure(self, user_id: str, display_name: str | None) -> None:
        row = self.profiles.setdefault(
            user_id,
            {
                "display_name": None,
                "consented_at": None,
                "income_agreed_at": None,
                "profile": Profile(),
            },
        )
        row["display_name"] = row["display_name"] or display_name

    async def get_me(self, user_id: str) -> Me | None:
        row = self.profiles.get(user_id)
        if row is None:
            return None
        filled = sum(getattr(row["profile"], f) is not None for f in COMPLETION_FIELDS)
        return Me(
            user_id=user_id,
            display_name=row["display_name"] or "학생",
            hyin_verified=False,
            calendar_connected=user_id in self.tokens,
            lms=None,
            profile_completion=ProfileCompletion(filled=filled, total=len(COMPLETION_FIELDS)),
            consented=row["consented_at"] is not None,
            income_info_consented=row["income_agreed_at"] is not None,
            unread_notifications=0,
        )

    async def get_profile(self, user_id: str) -> Profile | None:
        row = self.profiles.get(user_id)
        return row["profile"] if row else None

    async def update_profile(self, user_id: str, values: dict[str, Any]) -> None:
        row = self.profiles[user_id]
        row["profile"] = row["profile"].model_copy(update=values)

    async def get_consents(self, user_id: str) -> Consents:
        row = self.profiles.get(user_id)
        if row is None:
            return Consents(terms_privacy=False, income_info=False)
        return Consents(
            terms_privacy=row["consented_at"] is not None,
            income_info=row["income_agreed_at"] is not None,
        )

    async def save_consent(
        self, user_id: str, version: str, agree_income_info: bool
    ) -> ConsentResult:
        now = datetime.now(UTC)
        row = self.profiles[user_id]
        row["consented_at"] = now
        self._set_income(row, agree_income_info, now)
        return ConsentResult(
            terms_agreed_at=now,
            privacy_agreed_at=now,
            income_info_agreed_at=row["income_agreed_at"],
            consent_version=version,
        )

    async def set_income_consent(self, user_id: str, agree: bool) -> IncomeConsentResult:
        row = self.profiles[user_id]
        self._set_income(row, agree, datetime.now(UTC))
        return IncomeConsentResult(income_info_agreed_at=row["income_agreed_at"])

    @staticmethod
    def _set_income(row: dict[str, Any], agree: bool, now: datetime) -> None:
        if agree:
            row["income_agreed_at"] = row["income_agreed_at"] or now
        else:  # 철회하면 소득 값도 지운다 (DB 제약과 같은 규칙)
            row["income_agreed_at"] = None
            row["profile"] = row["profile"].model_copy(update=dict.fromkeys(INCOME_FIELDS))

    async def get_settings(self, user_id: str) -> Settings:
        return self.settings.get(
            user_id,
            Settings(push_enabled=True, muted_notification_types=[], calendar_auto_lms=True),
        )

    async def update_settings(self, user_id: str, changes: dict[str, Any]) -> Settings:
        """실제 저장소처럼 보낸 항목만 얹는다(행이 없으면 기본값 위에)."""
        current = await self.get_settings(user_id)
        self.settings[user_id] = Settings(**{**current.model_dump(), **changes})
        return self.settings[user_id]

    async def save_google_tokens(self, user_id: str, access_token: str, refresh_token: str) -> None:
        self.tokens[user_id] = {"access_token": access_token, "refresh_token": refresh_token}

    async def delete(self, user_id: str) -> bool:
        """탈퇴. 실제 저장소는 cascade로 딸린 행을 지우므로 여기서도 토큰·설정을 함께 지운다."""
        had = self.profiles.pop(user_id, None) is not None
        self.tokens.pop(user_id, None)
        self.settings.pop(user_id, None)
        return had


class FakeMetaRepository:
    def __init__(self) -> None:
        self.departments = [
            Department(name="인공지능학과", college="소프트웨어융합대학", field_group="공학계열"),
            Department(name="경영학부", college="경상대학", field_group="사회계열"),
        ]
        self.events: list[tuple[str, str, UUID | None]] = []

    async def list_departments(self) -> list[Department]:
        return list(self.departments)

    async def department_exists(self, name: str) -> bool:
        return any(department.name == name for department in self.departments)

    async def record_event(
        self, user_id: str, event: str, opportunity_id: UUID | None = None
    ) -> None:
        self.events.append((user_id, event, opportunity_id))


class FakeOpportunityRepository:
    """피드 API 단위 테스트용. 받은 요청을 남기고 정해 둔 목록·집계를 돌려준다."""

    def __init__(self) -> None:
        self.refreshes: list[tuple[str, bool, bool]] = []  # (user_id, force, include_expired)
        self.queries: list[FeedQuery] = []
        self.items: list[OpportunityItem] = []
        self.next_cursor: str | None = None
        self.changed = 0
        self.details: dict[str, OpportunityDetail] = {}  # 공고 id → 상세. 없으면 404
        self.detail_calls: list[tuple[str, str, str | None]] = []  # (user_id, 공고 id, 이름)
        self.openable: set[str] = set()  # 표시를 붙일 수 있는 공고 id. 없으면 404
        self.marks: dict[tuple[str, str], tuple[str, datetime]] = {}  # (user, 공고) → (표시, 시각)
        self.mark_calls: list[
            tuple[str, str, str | None, str | None]
        ] = []  # (user_id, 공고 id, 표시, 이름). 지우면 표시·이름이 None
        self.counts = FeedCounts(
            eligible=0,
            new_eligible=0,
            undetermined=0,
            missing_info=0,
            needs_review=0,
            ineligible=0,
            deadline_soon=0,
        )

    async def refresh_judgments(
        self,
        user_id: str,
        *,
        now: datetime,
        force: bool = False,
        include_expired: bool = False,
        display_name: str | None = None,
    ) -> Refresh:
        self.refreshes.append((user_id, force, include_expired))
        return Refresh(judged=0, changed=self.changed)

    async def feed_page(self, user_id: str, query: FeedQuery, *, now: datetime) -> FeedPage:
        self.queries.append(query)
        return FeedPage(items=list(self.items), next_cursor=self.next_cursor)

    async def feed_counts(self, user_id: str, *, now: datetime) -> FeedCounts:
        return self.counts

    async def detail(
        self,
        user_id: str,
        opportunity_id: str,
        *,
        now: datetime,
        display_name: str | None = None,
    ) -> OpportunityDetail | None:
        self.detail_calls.append((user_id, opportunity_id, display_name))
        return self.details.get(opportunity_id)

    async def set_mark(
        self,
        user_id: str,
        opportunity_id: str,
        mark: str,
        *,
        now: datetime,
        display_name: str | None = None,
    ) -> datetime | None:
        self.mark_calls.append((user_id, opportunity_id, mark, display_name))
        if opportunity_id not in self.openable:
            return None
        old = self.marks.get((user_id, opportunity_id))
        at = old[1] if old and old[0] == mark else now
        self.marks[(user_id, opportunity_id)] = (mark, at)
        return at

    async def clear_mark(self, user_id: str, opportunity_id: str) -> None:
        self.mark_calls.append((user_id, opportunity_id, None, None))
        self.marks.pop((user_id, opportunity_id), None)


class FakeMetricsRepository:
    """지표 집계 대역. 받은 기간만 적어 두고 빈 집계를 돌려준다."""

    def __init__(self) -> None:
        self.periods: list[tuple[date, date]] = []

    async def metrics(self, period: tuple[date, date]) -> Metrics:
        self.periods.append(period)
        start, end = period
        empty = Ratio(numerator=0, denominator=0, rate=None)
        return Metrics(
            from_date=start,
            to_date=end,
            scenarios=ScenarioMetrics(
                runs=0,
                passed=0,
                success_rate=0.0,
                latency=Latency(p50_ms=0, p95_ms=0),
                cost_usd=0.0,
                llm_calls=0,
                by_scenario=[],
            ),
            eligibility=EligibilityMatrix(
                run_started_at=None,
                checks=0,
                correct=0,
                accuracy=0.0,
                rows=[],
                eligible_to_ineligible=0,
                ineligible_to_eligible=0,
            ),
            product=ProductMetrics(
                undetermined=UndeterminedRate(**empty.model_dump(), top_missing_fields=[]),
                profile_prompt=empty,
                prepare_conversion=empty,
                lms_connect=empty,
                weekly_return=empty,
            ),
        )


class FakeLogCursor:
    """agent_log가 쓰는 커서 흉내. `returning id`면 행을 하나 준다."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self.row


class FakeLogConnection:
    """실행 로그용 autocommit 연결 흉내(DB 없이 agent_run을 돌린다).

    쓴 문장을 statements에 모아 둬서, 테스트가 실행·도구 기록이 남았는지 본다.
    """

    autocommit = True

    def __init__(self, run_id: str = "00000000-0000-4000-8000-0000000000a1") -> None:
        self.run_id = run_id
        self.statements: list[tuple[str, Any]] = []

    async def execute(self, query: str, params: Any = None) -> FakeLogCursor:
        self.statements.append((query, params))
        if "returning id" not in query:
            return FakeLogCursor(None)
        if "agent_runs" in query:
            return FakeLogCursor({"id": self.run_id})
        return FakeLogCursor({"id": "00000000-0000-4000-8000-0000000000a2"})

    def wrote(self, needle: str) -> bool:
        return any(needle in query for query, _ in self.statements)

    def outputs(self) -> dict[str, Any]:
        """도구 이름 → 그 도구가 남긴 출력. 도구는 겹치지 않으니 넣은 순서로 짝지어 읽는다."""
        open_names: list[str] = []
        found: dict[str, Any] = {}
        for query, params in self.statements:
            if not isinstance(params, tuple):
                continue
            if "insert into tool_calls" in query:
                open_names.append(params[2])
            elif "update tool_calls set output" in query and open_names:
                value = params[0]
                found[open_names.pop()] = getattr(value, "obj", value)
        return found

    def tools(self) -> list[str]:
        """기록된 도구 이름(tool_calls에 넣은 순서대로)."""
        return [
            params[2]
            for query, params in self.statements
            if "insert into tool_calls" in query and isinstance(params, tuple)
        ]
