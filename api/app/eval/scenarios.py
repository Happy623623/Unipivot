"""테스트 시나리오(PRD 8장 표). 하나가 함수 하나다.

시나리오는 세계를 만들고(사용자·공고) 실제 엔드포인트를 부르며, `world.check`로 기대 결과에 닿았는지
본다. 다르면 그 자리에서 멈추고 실패로 남는다 — 뒤 단계가 앞 단계의 결과를 쓰기 때문이다.

판정·요건이 S01–S08, 포스터·준비하기·캘린더·알림이 S11–S14, LMS 과제가 S16–S18이다. PRD 8장의
P0는 S01–S18 열여덟 개이고, 여기 있는 것은 그중 **열다섯 개**다. 없는 것과 이유:

- S09(요건이 첨부에만 있는 공고)·S10(공지 수정 재수집): 입력이 실제 HWP·PDF 파일과 저장한 공지
  폴더다. 그 파일을 레포에 둔 뒤에 붙인다
- S15(강의계획서 가져오기): `POST /syllabi/extract`(F-14)를 아직 만들지 않았다
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import httpx

from app.eligibility import KST
from app.eval.fakes import (
    DB_COURSE_ID,
    poster_bytes,
    poster_deadline,
    poster_submit,
    sido_codes,
    tool_reply,
    youth_policy,
)
from app.eval.world import EvalWorld, Rule, Scenario
from app.extraction.validate import LOW_CONFIDENCE as LOW_CONFIDENCE_REASON
from app.prepare.guide import TOOL_NAME as GUIDE_TOOL

DEPARTMENT = "인공지능학과"
GRADE_RULE = Rule(1, "gpa_last_semester", "gte", 3.0)
CREDIT_RULE = Rule(2, "credits_last_semester", "gte", 12)
# 사전에 없는 서류라 모델에 묻는다(app/prepare/service.py). 녹화한 안내를 돌려준다
PROPOSAL = "아이디어 제안서"
FIXED_TITLE = "2026 창업 아이디어 공모전"  # S12에서 학생이 고쳐 적는 제목
YOUTH_MAX_AGE = 34  # 청년정책 나이 상한(S07의 경계값)
PROPOSAL_GUIDE = tool_reply(
    GUIDE_TOOL,
    documents=[
        {
            "name": PROPOSAL,
            "issuer": "본인 작성",
            "how_to": "주최 측 양식에 맞춰 직접 씁니다.",
            "lead_days": 0,
            "effort_minutes": 120,
        }
    ],
)


# ── S01–S03: 같은 장학 공지, 프로필 셋 ───────────────────────────────────────


async def s01(world: EvalWorld) -> None:
    """ERICA 장학 공지, 평점 요건 충족 프로필 → 지원 가능 → 서류 안내 → 역산 일정 생성."""
    await world.department(DEPARTMENT)
    student = await world.user(
        department=DEPARTMENT,
        grade=3,
        enrollment_status="enrolled",
        gpa_last_semester=3.5,
        credits_last_semester=15,
    )
    opportunity = await world.add(
        "2026-2학기 ERICA 성적우수 장학",
        days=14,
        requirements=(GRADE_RULE, CREDIT_RULE),
        documents=("장학금 신청서", "재학증명서", PROPOSAL),
    )
    world.records(PROPOSAL_GUIDE)
    client = world.client(student)

    detail = await _detail(world, client, opportunity)
    await world.judged("판정", expected="eligible", actual=detail["eligibility"]["status"])
    await world.check(
        "화면 라벨", expected="eligible", actual=detail["eligibility"]["display_status"]
    )

    started = await client.post(world.path(f"/opportunities/{opportunity}/prepare"), json={})
    await world.check("준비하기 시작", expected=202, actual=started.status_code)
    run = await world.wait_run(client, started.json()["run_id"])
    await world.check("준비하기 실행", expected="succeeded", actual=run["status"])

    documents = run["result"]["documents"]
    await world.check("서류 수", expected=3, actual=len(documents))
    await world.check(
        "서류 안내 채움", expected=3, actual=sum(1 for item in documents if item["issuer"])
    )
    # 역산: 서류 할 일 3개 + 신청 제출 1개, 모두 마감일보다 앞이다
    deadline = _day(detail["deadline_at"])
    tasks = run["result"]["tasks"]
    await world.check("할 일 수", expected=4, actual=len(tasks))
    await world.check(
        "마감일보다 앞", expected=True, actual=all(task["due_date"] < deadline for task in tasks)
    )

    planner = await client.get(
        world.path("/planner/tasks"), params={"from": world.today.isoformat(), "to": deadline}
    )
    await world.check(
        "플래너에 보임",
        expected=4,
        actual=sum(1 for task in planner.json()["items"] if task["source"] == "prep_plan"),
    )


async def s02(world: EvalWorld) -> None:
    """같은 공지, 평점 미달 프로필 → 지원 어려움 + 탈락 사유."""
    await world.department(DEPARTMENT)
    student = await world.user(
        department=DEPARTMENT, grade=3, gpa_last_semester=2.5, credits_last_semester=15
    )
    opportunity = await world.add(
        "2026-2학기 ERICA 성적우수 장학", days=14, requirements=(GRADE_RULE, CREDIT_RULE)
    )
    client = world.client(student)

    detail = await _detail(world, client, opportunity)
    eligibility = detail["eligibility"]
    await world.judged("판정", expected="ineligible", actual=eligibility["status"])
    await world.check("화면 라벨", expected="ineligible", actual=eligibility["display_status"])
    await world.check("물어볼 항목 없음", expected=[], actual=eligibility["missing_fields"])
    failed = [row for row in eligibility["conditions"] if row["outcome"] == "fail"]
    await world.check(
        "탈락 조건", expected=["gpa_last_semester"], actual=[row["field"] for row in failed]
    )
    await world.check(
        "사유 한 줄", expected=True, actual=bool((eligibility["reason_text"] or "").strip())
    )


async def s03(world: EvalWorld) -> None:
    """같은 공지, 평점 미입력 프로필 → 정보 필요 → 평점 입력 → 재판정."""
    await world.department(DEPARTMENT)
    student = await world.user(department=DEPARTMENT, grade=3, credits_last_semester=15)
    opportunity = await world.add(
        "2026-2학기 ERICA 성적우수 장학", days=14, requirements=(GRADE_RULE, CREDIT_RULE)
    )
    client = world.client(student)

    before = (await _detail(world, client, opportunity))["eligibility"]
    await world.judged("판정", expected="undetermined", actual=before["status"])
    await world.check("화면 라벨", expected="missing_info", actual=before["display_status"])
    await world.check(
        "물어볼 항목", expected=["gpa_last_semester"], actual=before["missing_fields"]
    )

    patched = await client.patch(
        world.path("/me/profile"), json={"gpa_last_semester": 3.5, "gpa_scale": 4.5}
    )
    await world.check("평점 입력", expected=200, actual=patched.status_code)

    after = (await _detail(world, client, opportunity))["eligibility"]
    await world.judged("다시 판정", expected="eligible", actual=after["status"])
    await world.check("물어볼 항목 없음", expected=[], actual=after["missing_fields"])


# ── S04–S05: "또는"과 예외 ──────────────────────────────────────────────────


async def s04(world: EvalWorld) -> None:
    """ "평점 3.0 이상 또는 8구간 이하" 공고, 평점 미입력·6구간 → 지원 가능(3치 판정)."""
    student = await world.user(income_bracket=6)
    opportunity = await world.add(
        "소득연계 교내 장학",
        days=20,
        requirements=(GRADE_RULE, Rule(1, "income_bracket", "lte", 8)),
    )
    client = world.client(student)

    eligibility = (await _detail(world, client, opportunity))["eligibility"]
    await world.judged("판정", expected="eligible", actual=eligibility["status"])
    await world.check("묶음 수", expected=1, actual=len(eligibility["clauses"]))
    await world.check("묶음 결과", expected="pass", actual=eligibility["clauses"][0]["outcome"])
    # 충족한 묶음의 빈 항목은 묻지 않는다(판정엔진_규칙 6장)
    await world.check("물어볼 항목 없음", expected=[], actual=eligibility["missing_fields"])
    unknown = [row["field"] for row in eligibility["conditions"] if row["outcome"] == "unknown"]
    await world.check("모름 조건", expected=["gpa_last_semester"], actual=unknown)


async def s05(world: EvalWorld) -> None:
    """ "12학점 이상(단, 4학년 9학점)" 공고, 4학년 10학점 → 지원 가능 / 3학년 10학점 → 지원 어려움.

    묶음 1 = (4학년 또는 12학점 이상), 묶음 2 = (4학년이 아님 또는 9학점 이상)으로 저장한다
    (판정엔진_규칙 5장).
    """
    senior = await world.user(grade=4, credits_last_semester=10)
    junior = await world.user(grade=3, credits_last_semester=10)
    opportunity = await world.add(
        "국가장학금 연계 교내 장학",
        days=18,
        requirements=(
            Rule(1, "grade", "eq", 4),
            Rule(1, "credits_last_semester", "gte", 12),
            Rule(2, "grade", "neq", 4),
            Rule(2, "credits_last_semester", "gte", 9),
        ),
    )

    senior_view = await _detail(world, world.client(senior), opportunity)
    await world.judged(
        "4학년 10학점", expected="eligible", actual=senior_view["eligibility"]["status"]
    )
    junior_view = await _detail(world, world.client(junior), opportunity)
    await world.judged(
        "3학년 10학점", expected="ineligible", actual=junior_view["eligibility"]["status"]
    )
    await world.check(
        "불충족 묶음",
        expected=[1],
        actual=[
            clause["clause_no"]
            for clause in junior_view["eligibility"]["clauses"]
            if clause["outcome"] == "fail"
        ],
    )


# ── S06–S07: 온통청년 정책(LLM 없는 코드 변환) ──────────────────────────────


async def s06(world: EvalWorld) -> None:
    """온통청년 정책, 거주지역 불일치 → 지원 어려움 + 지역 사유."""
    student = await world.user(region_sido="경기도", region_sigungu="안산시")
    opportunity = await world.youth(
        youth_policy(
            plcyNo="eval-S06",
            plcyNm="서울 청년 월세 지원",
            zipCd=sido_codes("서울특별시"),
        )
    )
    client = world.client(student)

    detail = await _detail(world, client, opportunity)
    await world.check("출처", expected="youth_policy", actual=detail["source_type"])
    eligibility = detail["eligibility"]
    await world.check(
        "지역 조건", expected=["region"], actual=[row["field"] for row in eligibility["conditions"]]
    )
    await world.judged("판정", expected="ineligible", actual=eligibility["status"])
    await world.check("탈락 조건", expected="fail", actual=eligibility["conditions"][0]["outcome"])
    await world.check(
        "지역 사유", expected=True, actual="지역" in (eligibility["reason_text"] or "")
    )


async def s07(world: EvalWorld) -> None:
    """온통청년 정책, 판정 기준일에 만 34세 마지막 날 → 기준일 기준으로 정확히 판정.

    신청 기간이 기준일에 끝나므로 판정 기준일은 그 하루다(판정엔진_규칙 8장). 그날 만 34세인 마지막
    날인 학생(다음 날 35세)은 지원 가능이고, 하루 먼저 태어난 학생은 이미 35세라 지원 어려움이다.
    날짜는 모두 주입한 시계에서 센다 — --now를 바꿔도 같은 경계를 본다.

    나이는 프로필 값이라 tool_calls에 남기지 않는다(world.check 설명). 그래서 몇 살인지 대신
    "조건이 맞는가"로 확인한다.
    """
    basis = world.today
    birthday = _born_on_last_day(basis, YOUTH_MAX_AGE)
    last_day = await world.user(birth_date=birthday.isoformat())
    one_day_earlier = await world.user(birth_date=(birthday - timedelta(days=1)).isoformat())
    opportunity = await world.youth(
        youth_policy(
            plcyNo="eval-S07",
            plcyNm="청년 희망적금 매칭 지원",
            aplyPrdSeCd="0057001",  # 특정 기간
            aplyYmd=f"{basis - timedelta(days=41):%Y%m%d} ~ {basis:%Y%m%d}",
            sprtTrgtMinAge="19",
            sprtTrgtMaxAge=str(YOUTH_MAX_AGE),
        )
    )

    view = await _detail(world, world.client(last_day), opportunity)
    await world.check(
        "판정 기준일", expected=basis.isoformat(), actual=view["eligibility"]["basis_date"]
    )
    condition = view["eligibility"]["conditions"][0]
    await world.check("나이 조건", expected="age", actual=condition["field"])
    await world.check("나이 조건 충족", expected="pass", actual=condition["outcome"])
    # 보이는 나이도 맞아야 한다. 나이 자체는 남기지 않으므로 "맞는가"만 적는다
    await world.check(
        "보이는 나이",
        expected=True,
        actual=condition["user_value_text"] == f"만 {YOUTH_MAX_AGE}세",
    )
    await world.judged(
        "만 34세 마지막 날", expected="eligible", actual=view["eligibility"]["status"]
    )

    older = await _detail(world, world.client(one_day_earlier), opportunity)
    await world.judged(
        "하루 먼저 태어난 학생", expected="ineligible", actual=older["eligibility"]["status"]
    )
    await world.check(
        "하루 먼저 태어난 학생의 나이 조건",
        expected="fail",
        actual=older["eligibility"]["conditions"][0]["outcome"],
    )
    await world.check(
        "하루 먼저 태어난 학생의 보이는 나이",
        expected=True,
        actual=older["eligibility"]["conditions"][0]["user_value_text"]
        == f"만 {YOUTH_MAX_AGE + 1}세",
    )


# ── S08: 모호한 요건 ────────────────────────────────────────────────────────


async def s08(world: EvalWorld) -> None:
    """요건이 모호한 공고("성적 우수자") → 원문 확인 필요 배지."""
    student = await world.user(grade=3, gpa_last_semester=3.5)
    opportunity = await world.add(
        "총장 추천 우수인재 장학",
        days=12,
        needs_review=True,
        extraction_confidence=0.55,
        requirements=(Rule(1, "other", "eq", {"text": "성적 우수자"}, is_ambiguous=True),),
    )
    client = world.client(student)

    detail = await _detail(world, client, opportunity)
    eligibility = detail["eligibility"]
    await world.judged("판정", expected="undetermined", actual=eligibility["status"])
    await world.check("화면 라벨", expected="needs_review", actual=eligibility["display_status"])
    await world.check("물어볼 항목 없음", expected=[], actual=eligibility["missing_fields"])
    condition = eligibility["conditions"][0]
    await world.check("모호 표시", expected=True, actual=condition["is_ambiguous"])
    # 프로필로 판정할 수 없는 조건은 other로 들어온다(판정엔진_규칙 10장 8번) → 판정 불가
    await world.check(
        "판정할 수 없는 조건", expected="unsupported_field", actual=condition["unknown_reason"]
    )
    await world.check("배지", expected=True, actual=detail["needs_review"])

    # 피드에서도 같은 배지가 보인다. 쪽을 넘겨 찾으므로 DB에 다른 공고가 많아도 된다
    card = await world.feed_card(client, opportunity)
    await world.check("피드 카드", expected=True, actual=card is not None)
    await world.check("피드 배지", expected=True, actual=bool(card and card["needs_review"]))
    await world.check(
        "피드 라벨",
        expected="needs_review",
        actual=card and card["eligibility"]["display_status"],
    )


# ── S11–S12: 포스터 ────────────────────────────────────────────────────────


async def s11(world: EvalWorld) -> None:
    """공모전 포스터 사진 업로드 → 추출·확인 화면 → 본인 피드에만 표시."""
    student = await world.user(enrollment_status="enrolled", grade=3)
    other = await world.user(enrollment_status="enrolled")
    world.records(poster_submit(world.today))
    client = world.client(student)

    uploaded = await client.post(
        world.path("/files"),
        files={"file": ("poster.jpg", poster_bytes(), "image/jpeg")},
        data={"kind": "poster"},
    )
    await world.check("포스터 올리기", expected=201, actual=uploaded.status_code)
    await world.check("저장소에 담김", expected=1, actual=len(world.storage.files))

    started = await client.post(
        world.path("/posters/extract"), json={"file_id": uploaded.json()["file_id"]}
    )
    await world.check("추출 시작", expected=202, actual=started.status_code)
    run_id = started.json()["run_id"]
    run = await world.wait_run(client, run_id)
    await world.check("추출 실행", expected="succeeded", actual=run["status"])

    draft = run["result"]["draft"]
    await world.check("제목", expected="2026 전국 대학생 SW 창업 아이디어톤", actual=draft["title"])
    await world.check("종류", expected="contest", actual=draft["category"])
    await world.check(
        "마감일",
        expected=poster_deadline(world.today).date().isoformat(),
        actual=_day(draft["deadline_at"]),
    )
    await world.check("확인할 칸 없음", expected=[], actual=draft["low_confidence_fields"])
    await world.check("요건 수", expected=1, actual=len(draft["requirements"]))
    await world.check("서류 수", expected=2, actual=len(draft["documents"]))

    confirmed = await client.post(
        world.path("/posters/confirm"), json={"run_id": run_id, "draft": draft}
    )
    await world.check("공고 등록", expected=201, actual=confirmed.status_code)
    opportunity = confirmed.json()["opportunity_id"]

    detail = await _detail(world, client, opportunity)
    await world.check("내가 올린 포스터", expected=True, actual=detail["uploaded_by_me"])
    await world.judged("판정", expected="eligible", actual=detail["eligibility"]["status"])

    mine = await world.feed_card(client, opportunity)
    await world.check("내 피드에 보임", expected=True, actual=mine is not None)
    # 남의 피드에는 어느 쪽에도 없어야 한다(공개 범위 규칙). 그래서 쪽을 끝까지 넘겨 본다
    theirs = await world.feed_card(world.client(other), opportunity)
    await world.check("남의 피드에 없음", expected=None, actual=theirs)


async def s12(world: EvalWorld) -> None:
    """흐릿하거나 기울어진 포스터 → 저신뢰도 배지, 수정 가능."""
    student = await world.user(enrollment_status="enrolled", grade=3)
    world.records(
        poster_submit(
            world.today,
            title="창업 아이디어",  # 큰 글씨만 읽혔다
            confidence=0.42,
            deadline=None,  # 기울어져 날짜를 못 읽었다
            apply_start=None,
        )
    )
    client = world.client(student)

    uploaded = await client.post(
        world.path("/files"),
        files={"file": ("blurry.jpg", poster_bytes(b"blurry"), "image/jpeg")},
        data={"kind": "poster"},
    )
    run_id = (
        await client.post(
            world.path("/posters/extract"), json={"file_id": uploaded.json()["file_id"]}
        )
    ).json()["run_id"]
    run = await world.wait_run(client, run_id)
    await world.check("추출 실행", expected="succeeded", actual=run["status"])

    draft = run["result"]["draft"]
    await world.check("낮은 신뢰도", expected=True, actual=draft["extraction_confidence"] < 0.6)
    await world.check(
        "확인할 칸",
        expected=["title", "deadline_at"],
        actual=draft["low_confidence_fields"],
    )
    await world.check("마감일 비어 있음", expected=None, actual=draft["deadline_at"])

    # 학생이 제목과 마감일을 고쳐 보낸다(요건·서류는 그대로)
    deadline = poster_deadline(world.today)
    fixed = {**draft, "title": FIXED_TITLE, "deadline_at": deadline.isoformat()}
    confirmed = await client.post(
        world.path("/posters/confirm"), json={"run_id": run_id, "draft": fixed}
    )
    await world.check("고쳐서 등록", expected=201, actual=confirmed.status_code)

    detail = await _detail(world, client, confirmed.json()["opportunity_id"])
    await world.check("고친 제목", expected=FIXED_TITLE, actual=detail["title"])
    await world.check(
        "고친 마감일", expected=deadline.date().isoformat(), actual=_day(detail["deadline_at"])
    )
    await world.check("배지", expected=True, actual=detail["needs_review"])
    await world.check(
        "배지 이유", expected=[LOW_CONFIDENCE_REASON], actual=detail["review_reasons"]
    )
    # 재학생 조건은 그대로 남았다 → 고쳐 등록해도 판정은 된다
    await world.judged("판정", expected="eligible", actual=detail["eligibility"]["status"])


# ── S13: 준비하기 → 캘린더 ──────────────────────────────────────────────────


async def s13(world: EvalWorld) -> None:
    """준비하기 → (처음이면 캘린더 연결) → 등록 → 다시 누르기 → 마감일 이벤트 1개만 존재."""
    student = await world.user(grade=3, gpa_last_semester=3.5, credits_last_semester=15)
    opportunity = await world.add(
        "2026 동계 교환학생 장학",
        days=21,
        requirements=(GRADE_RULE,),
        documents=("재학증명서",),  # 모두 서류 사전에 있어 모델을 부르지 않는다
    )
    client = world.client(student)

    started = await client.post(world.path(f"/opportunities/{opportunity}/prepare"), json={})
    run = await world.wait_run(client, started.json()["run_id"])
    await world.check("준비하기 실행", expected="succeeded", actual=run["status"])

    first = await client.post(world.path("/calendar/events"), json={"opportunity_id": opportunity})
    await world.check("연결 전", expected=409, actual=first.status_code)
    await world.check(
        "연결하라는 코드", expected="CALENDAR_NOT_CONNECTED", actual=first.json()["error"]["code"]
    )

    connected = await client.post(
        world.path("/auth/google/tokens"),
        json={"provider_token": "eval-access", "provider_refresh_token": "eval-refresh"},
    )
    await world.check("캘린더 연결", expected=200, actual=connected.status_code)

    added = await client.post(world.path("/calendar/events"), json={"opportunity_id": opportunity})
    await world.check("등록", expected=201, actual=added.status_code)
    await world.check(
        "Google 일정 번호", expected=True, actual=bool(added.json()["external_event_id"])
    )

    again = await client.post(world.path("/calendar/events"), json={"opportunity_id": opportunity})
    await world.check("다시 누르기", expected=200, actual=again.status_code)
    await world.check("같은 일정", expected=added.json()["id"], actual=again.json()["id"])

    rows = await world.rows(
        "select count(*) as count from calendar_events where user_id = %s and opportunity_id = %s",
        student,
        opportunity,
    )
    await world.check("우리 기록 1건", expected=1, actual=rows[0]["count"])
    await world.check("Google 일정 1건", expected=1, actual=len(world.calendar.events))
    await world.check(
        "Google 일정 제목",
        expected=["[마감] 2026 동계 교환학생 장학"],
        actual=list(world.calendar.titles.values()),
    )

    detail = await _detail(world, client, opportunity)
    await world.check("상세에 1건", expected=1, actual=len(detail["prep"]["calendar_events"]))


# ── S14: 마감 임박 알림 ────────────────────────────────────────────────────


async def s14(world: EvalWorld) -> None:
    """마감 D-3·D-1 공고 → 웹 푸시와 알림함에 한 번씩, 같은 알림 중복 없음.

    예약(하루 한 번)과 발송(5분마다)은 스케줄러가 부르는 작업이라 시나리오가 서비스 키로 직접 부른다.
    예약한 뒤 그날이 되어야 보내지므로 중간에 시계를 옮긴다(`world.travel`).

    실제 푸시 발송은 F-33이다. 여기서는 "푸시를 보낼 수 있는 알림"으로 세고, 알림함을 눈으로 본다.
    """
    student = await world.user(grade=3, gpa_last_semester=3.5)
    opportunity = await world.add("마감 임박 교내 장학", days=4.5, requirements=(GRADE_RULE,))
    client, jobs = world.client(student), world.internal()

    # 판정이 저장되어야 알림을 예약한다(적격이거나 준비한 공고만)
    detail = await _detail(world, client, opportunity)
    await world.judged("판정", expected="eligible", actual=detail["eligibility"]["status"])

    first = await jobs.post(world.path("/internal/jobs/schedule-notifications"))
    await world.check("예약", expected=200, actual=first.status_code)
    await world.check("D-3·D-1 두 건", expected=2, actual=first.json()["by_type"]["deadline_soon"])
    await world.check("새로 만든 알림", expected=2, actual=first.json()["created"])
    # 상세를 열어 본 공고는 "새 공고" 알림을 만들지 않는다(ERD: opportunity_views에 행이 없는 공고)
    await world.check(
        "새 공고 알림 없음", expected=0, actual=first.json()["by_type"]["new_eligible"]
    )

    again = (await jobs.post(world.path("/internal/jobs/schedule-notifications"))).json()
    await world.check("다시 예약해도 안 늘어남", expected=0, actual=again["created"])
    await world.check("지운 것 없음", expected=0, actual=again["removed"])

    # 아직 보낼 때가 아니다(마감 임박은 D-3 아침에 보낸다)
    early = (await jobs.post(world.path("/internal/jobs/send-notifications"))).json()
    await world.check("D-3 전에는 보낼 것이 없음", expected=0, actual=early["due"])
    await world.check(
        "알림함에 마감 알림 없음", expected=[], actual=await _deadlines(world, client)
    )

    world.travel(days=2)  # D-3 아침이 지났다
    sent = (await jobs.post(world.path("/internal/jobs/send-notifications"))).json()
    await world.check("D-3 발송", expected=1, actual=sent["sent"])
    await world.check("푸시 구독 없음", expected=0, actual=sent["pushable"])
    await world.check("알림함에 D-3 하나", expected=["D-3"], actual=await _deadlines(world, client))

    world.travel(days=2)  # D-1 아침이 지났다
    await jobs.post(world.path("/internal/jobs/send-notifications"))
    await world.check(
        "D-3·D-1 한 번씩", expected=["D-1", "D-3"], actual=sorted(await _deadlines(world, client))
    )

    # 보낸 알림을 또 보내지 않는다
    nothing = (await jobs.post(world.path("/internal/jobs/send-notifications"))).json()
    await world.check("보낼 것 없음", expected=0, actual=nothing["due"])
    rows = await world.rows(
        "select count(*) as count from notifications where user_id = %s and type = 'deadline_soon'",
        student,
    )
    await world.check("알림 행도 두 개뿐", expected=2, actual=rows[0]["count"])

    box = (await client.get(world.path("/notifications"))).json()
    await world.check("안 읽은 수", expected=2, actual=box["unread_count"])
    read = await client.post(world.path("/notifications/read"), json={"all": True})
    await world.check("읽음 처리", expected=0, actual=read.json()["unread_count"])


# ── S16–S18: LMS 과제 (녹화 응답) ───────────────────────────────────────────
# 전/후 두 벌을 두는 대신 녹화한 응답을 시나리오가 고친다(app/eval/fakes.py의 RecordedLearningX).

LMS_TOKEN = "18742~evalRecordedTokenValue00000000"  # 녹화한 토큰 **모양**(값은 가짜다)
NEW_ASSIGNMENT = 9_901_900  # 시나리오 전용 번호대(fakes.py 머리말)
NEW_TITLE = "실습 4주차 결과 제출"
OPEN_ASSIGNMENT = 9_901_242  # 연결할 때 이미 있던 미제출 과제(실습 2주차)
OPEN_TITLE = "실습 2주차 결과 제출"
OPEN_DUE_DAYS = 8  # 그 과제의 마감(녹화 기준 시계에서 며칠 뒤)
NEW_DUE_DAYS = 12  # 새로 올라온 과제의 마감
MOVED_DUE_DAYS = 15  # 마감이 밀린 뒤


async def s16(world: EvalWorld) -> None:
    """LearningX 연결 → 새 과제가 올라옴 → 다음 동기화에서 캘린더·플래너에 1건 + 알림.

    연결은 과목 목록까지만 받는다(명세 8장). 과제는 바로 뒤에 부르는 첫 동기화가 받는다.
    """
    student = await world.user(grade=3)
    client, jobs = world.client(student), world.internal()
    await _connect_calendar(world, client)
    first = await _connect_lms(world, client)
    await world.check("과목 둘을 받음", expected=2, actual=first["courses"])
    # 처음 저장한 과제는 셋이다(미제출 1 · 이미 낸 것 1 · 채점까지 끝난 퀴즈 1)
    await world.check("과제 셋을 저장", expected=3, actual=first["assignments"]["new"])
    # 그중 캘린더·플래너·알림은 **마감이 있고 아직 내지 않은** 하나만(명세 9장)
    await world.check("캘린더에 1건", expected=1, actual=first["calendar_events"])
    # 주차 항목도 처음 받는다. 이 숫자가 0이면 앞 실행이 남긴 행이 있는 것이다(항목은 과목 공통 표다)
    await world.check("주차 항목 1건을 처음 봄", expected=1, actual=first["new_module_items"])

    # 다음 주, 교수가 새 과제를 올렸다
    world.lms.add_assignment(DB_COURSE_ID, NEW_ASSIGNMENT, NEW_TITLE, in_days=NEW_DUE_DAYS)
    world.travel(minutes=6)  # 5분 안에 또 부르면 서버가 건너뛴다(명세 9장)
    result = await _sync(world, client)

    await world.check("새 과제 1건", expected=1, actual=result["assignments"]["new"])
    await world.check("캘린더에 1건 더", expected=1, actual=result["calendar_events"])
    await world.check("시각 고친 일정 없음", expected=0, actual=result["calendar_moved"])
    await world.check(
        "캘린더 일정 두 개(제목에 과목)",
        expected=[
            "[과제] 데이터베이스 · 실습 2주차 결과 제출",
            f"[과제] 데이터베이스 · {NEW_TITLE}",
        ],
        actual=sorted(world.calendar.titles.values()),
    )

    tasks = await _tasks(world, client)
    await world.check(
        "플래너에 할 일 두 개", expected=[OPEN_TITLE, NEW_TITLE], actual=sorted(tasks)
    )

    # 발송 작업은 DB 전체의 보낼 알림을 본다(남의 것도 센다). 그래서 "두 건 이상"만 보고,
    # 정확한 확인은 내 알림함으로 한다
    sent = (await jobs.post(world.path("/internal/jobs/send-notifications"))).json()
    await world.check("보낼 알림이 있었다", expected=True, actual=sent["sent"] >= 2)
    await world.check(
        "알림함에 새 과제 두 건",
        expected=[OPEN_TITLE, NEW_TITLE],
        actual=sorted(await _assignment_notices(world, client)),
    )


async def s17(world: EvalWorld) -> None:
    """LMS 과제 마감 변경 → 기존 캘린더 일정의 시각만 고친다(새 일정 없음)."""
    student = await world.user(grade=3)
    client = world.client(student)
    await _connect_calendar(world, client)
    await _connect_lms(world, client)
    inserted, event_id = world.calendar.inserts, next(iter(world.calendar.events))
    before = len(await _tasks(world, client, done=None))
    await world.check("할 일 하나로 시작", expected=1, actual=before)

    world.lms.change_due(OPEN_ASSIGNMENT, in_days=MOVED_DUE_DAYS)  # 마감이 한 주 밀렸다
    world.travel(minutes=6)
    result = await _sync(world, client)

    await world.check("마감 바뀐 과제 1건", expected=1, actual=result["assignments"]["due_changed"])
    await world.check("새로 넣은 일정 없음", expected=0, actual=result["calendar_events"])
    await world.check("시각 고친 일정 1건", expected=1, actual=result["calendar_moved"])
    await world.check("Google에 새로 넣지 않음", expected=inserted, actual=world.calendar.inserts)
    await world.check("일정은 그대로 하나", expected=[event_id], actual=list(world.calendar.events))
    # 기준은 **녹화가 센 시각**(시나리오 시작 시각)이다. travel 뒤의 today로 세면 자정 근처에서
    # 하루가 밀려, 기능과 무관하게 깨진다
    moved_day = (world.lms.now.astimezone(KST) + timedelta(days=MOVED_DUE_DAYS)).date()
    await world.check(
        "끝 시각이 새 마감",
        expected=datetime.combine(moved_day, time(23, 59, 59), tzinfo=KST),
        actual=world.calendar.events[event_id].ends_at.astimezone(KST),
    )
    await world.check(
        "할 일 날짜도 옮겨짐",
        expected=[moved_day.isoformat()],
        actual=[task for title, task in await _task_dates(world, client) if title == OPEN_TITLE],
    )
    after = len(await _tasks(world, client, done=None))
    await world.check("할 일이 늘지 않음", expected=1, actual=after)


async def s18(world: EvalWorld) -> None:
    """LMS 과제 제출 → 플래너 할 일 자동 완료, 아직 보내지 않은 알림 취소."""
    student = await world.user(grade=3)
    client, jobs = world.client(student), world.internal()
    await _connect_calendar(world, client)
    await _connect_lms(world, client)
    await world.check(
        "할 일 하나", expected=[OPEN_TITLE], actual=sorted(await _tasks(world, client))
    )
    pending = await world.rows(
        "select count(*) as count from notifications where user_id = %s and sent_at is null",
        student,
    )
    await world.check("보내기 전 알림 하나", expected=1, actual=pending[0]["count"])

    world.lms.submit(OPEN_ASSIGNMENT)  # 학생이 냈다
    world.travel(minutes=6)
    result = await _sync(world, client)

    await world.check("제출로 바뀐 과제 1건", expected=1, actual=result["assignments"]["submitted"])
    await world.check("남은 할 일 없음", expected=[], actual=await _tasks(world, client))
    await world.check(
        "자동 완료된 할 일 하나",
        expected=[OPEN_TITLE],
        actual=await _tasks(world, client, done=True),
    )
    left = await world.rows(
        "select count(*) as count from notifications where user_id = %s and sent_at is null",
        student,
    )
    await world.check("보내지 않은 알림은 지워짐", expected=0, actual=left[0]["count"])
    # 발송 작업을 돌려도 내 알림함에는 아무것도 들어오지 않는다(지워졌으니까).
    # `due`는 DB 전체 기준이라 남의 알림이 섞일 수 있어 내 행으로 센다
    await jobs.post(world.path("/internal/jobs/send-notifications"))
    mine = await world.rows(
        "select count(*) as count from notifications where user_id = %s", student
    )
    await world.check("내 알림함에 남은 것 없음", expected=0, actual=mine[0]["count"])


async def _connect_calendar(world: EvalWorld, client: httpx.AsyncClient) -> None:
    """Google 캘린더를 먼저 연결한다(설정은 기본 켬이라 과제 마감이 자동으로 들어간다)."""
    connected = await client.post(
        world.path("/auth/google/tokens"),
        json={"provider_token": "eval-access", "provider_refresh_token": "eval-refresh"},
    )
    await world.check("캘린더 연결", expected=200, actual=connected.status_code)


async def _connect_lms(world: EvalWorld, client: httpx.AsyncClient) -> dict:
    """LearningX를 연결하고(과목까지) 첫 동기화로 과제를 받는다. 그 결과를 돌려준다."""
    connected = await client.post(world.path("/lms/connection"), json={"access_token": LMS_TOKEN})
    await world.check("LearningX 연결", expected=201, actual=connected.status_code)
    body = connected.json()
    await world.check("수강 과목 둘", expected=2, actual=body["courses"])
    run = await world.wait_run(client, body["first_sync_run_id"])
    await world.check("연결 실행", expected="succeeded", actual=run["status"])
    # 연결은 과목까지다. 과제는 바로 뒤 동기화가 받는다(건너뛰지 않아야 한다)
    return await _sync(world, client)


async def _sync(world: EvalWorld, client: httpx.AsyncClient) -> dict:
    started = await client.post(world.path("/lms/sync"))
    await world.check("동기화 시작", expected=202, actual=started.status_code)
    run = await world.wait_run(client, started.json()["run_id"])
    await world.check("동기화 실행", expected="succeeded", actual=run["status"])
    result: dict = run["result"]
    return result


async def _tasks(world: EvalWorld, client: httpx.AsyncClient, done: bool | None = False) -> list:
    """플래너에 보이는 LMS 과제 할 일 제목(기본은 아직 안 끝낸 것)."""
    return [title for title, _ in await _task_dates(world, client, done)]


async def _task_dates(
    world: EvalWorld, client: httpx.AsyncClient, done: bool | None = False
) -> list:
    planner = await client.get(
        world.path("/planner/tasks"),
        params={
            "from": world.today.isoformat(),
            "to": (world.today + timedelta(days=30)).isoformat(),
        },
    )
    return [
        (task["title"], task["due_date"])
        for task in planner.json()["items"]
        if task["source"] == "lms_assignment" and (done is None or task["is_done"] == done)
    ]


async def _assignment_notices(world: EvalWorld, client: httpx.AsyncClient) -> list[str]:
    """알림함에 보이는 새 과제 알림의 과제 제목(제목은 과목, 본문이 "과제 · 마감 …"이다)."""
    box = (await client.get(world.path("/notifications"))).json()
    return [
        item["body"].split(" · 마감", 1)[0]
        for item in box["items"]
        if item["type"] == "new_assignment"
    ]


async def _deadlines(world: EvalWorld, client: httpx.AsyncClient) -> list[str]:
    """알림함에 보이는 마감 임박 알림의 D-day."""
    box = (await client.get(world.path("/notifications"))).json()
    return [
        item["body"].rsplit("· ", 1)[-1] for item in box["items"] if item["type"] == "deadline_soon"
    ]


# ── 공통 ───────────────────────────────────────────────────────────────────


async def _detail(world: EvalWorld, client: httpx.AsyncClient, opportunity: str) -> dict:
    response = await client.get(world.path(f"/opportunities/{opportunity}"))
    response.raise_for_status()
    body: dict = response.json()
    return body


def _born_on_last_day(on: date, age: int) -> date:
    """on 날짜에 만 age세인 마지막 날이 되도록 하는 생일(다음 날 age+1세가 된다)."""
    turns = on + timedelta(days=1)
    try:
        return turns.replace(year=turns.year - age - 1)
    except ValueError:  # 2월 29일생: 그 해가 윤년이 아니면 민법상 3월 1일에 나이가 오른다
        return turns.replace(year=turns.year - age - 1, day=28)


def _day(moment: str | None) -> str | None:
    """KST 오프셋이 붙은 시각의 날짜(YYYY-MM-DD)."""
    return datetime.fromisoformat(moment).date().isoformat() if moment else None


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("S01", "장학 공지, 평점 충족 → 지원 가능 → 서류 안내 → 역산 일정", "P0", s01),
    Scenario("S02", "같은 공지, 평점 미달 → 지원 어려움 + 탈락 사유", "P0", s02),
    Scenario("S03", "같은 공지, 평점 미입력 → 정보 필요 → 입력 → 재판정", "P0", s03),
    Scenario("S04", '"평점 3.0 이상 또는 8구간 이하", 평점 미입력·6구간 → 지원 가능', "P0", s04),
    Scenario("S05", '"12학점 이상(단, 4학년 9학점)", 4학년·3학년 10학점', "P0", s05),
    Scenario("S06", "온통청년 정책, 거주지역 불일치 → 지원 어려움 + 지역 사유", "P0", s06),
    Scenario("S07", "온통청년 정책, 판정 기준일에 만 34세 마지막 날", "P0", s07),
    Scenario("S08", '요건이 모호한 공고("성적 우수자") → 원문 확인 필요 배지', "P0", s08),
    Scenario("S11", "공모전 포스터 업로드 → 추출·확인 → 본인 피드에만", "P0", s11),
    Scenario("S12", "흐릿한 포스터 → 저신뢰도 배지, 수정 가능", "P0", s12),
    Scenario("S13", "준비하기 → 캘린더 연결 → 등록 → 다시 눌러도 하나", "P0", s13),
    Scenario("S14", "마감 D-3·D-1 → 알림함에 한 번씩, 중복 없음", "P0", s14),
    Scenario("S16", "LMS 새 과제(녹화 응답) → 캘린더·플래너 1건 + 알림", "P0", s16),
    Scenario("S17", "LMS 과제 마감 변경 → 기존 캘린더 일정 수정, 새 이벤트 없음", "P0", s17),
    Scenario("S18", "LMS 과제 제출 → 플래너 자동 완료, 보내지 않은 알림 취소", "P0", s18),
)

BY_CODE = {scenario.code: scenario for scenario in SCENARIOS}


def pick(codes: list[str] | None) -> list[Scenario]:
    """번호로 고른다. 없는 번호는 그대로 알려 준다(오타를 조용히 넘기지 않게)."""
    if codes is None:
        return list(SCENARIOS)
    if not codes:
        raise KeyError("고를 시나리오 번호를 적어 주세요 (예: S01,S13)")
    if unknown := [code for code in codes if code not in BY_CODE]:
        raise KeyError(f"모르는 시나리오: {', '.join(unknown)}")
    return [BY_CODE[code] for code in codes]
