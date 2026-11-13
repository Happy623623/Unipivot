"""LearningX 응답 샘플 (2026-10-16 녹화, 개인정보·서명값 제거).

학교 LMS에서 실제로 받은 응답의 **모양**을 그대로 두고 값만 바꿨다(과목 번호·이름·사용자 번호).
녹화에서 확인한 것 중 이 샘플이 담은 것:

- `users/self`에 email·login_id가 없다(학교 설정). 이름·아바타만 온다
- 과목명은 `202620HY23525_데이터베이스` 꼴이고 `course_code`도 같은 문자열이다
- `term.end_at`이 null이다 → 학기 종료일은 과목의 `end_at`에서 본다
- 학생 등록이 아닌 과목(조교·청강)과 `workflow_state`가 `unpublished`인 과목이 섞일 수 있다
- 과목명 꼴이 다른 과목도 있을 수 있다(계절·비정규 과목) → 계획서 링크를 만들지 않는다

과제 샘플에서 확인한 것(F-51, 과제 17건 녹화):

- `due_at`이 null이고 `lock_at`만 있는 과제가 있다(17건 중 5건) → 마감은 `due_at ?? lock_at`이다
- `has_submitted_submissions`는 과목 전체 기준이라 내가 내지 않은 과제에도 true다 → 쓰지 않는다
- 퀴즈(`submission_types: ["online_quiz"]`)는 자동 채점돼 `graded`로 온다(17건 중 4건)
- 제출한 과제의 `submission.submitted_at`이 제출 시각이다. 점수는 null일 수 있다(0점 과제)
- 시각은 모두 `...Z`(UTC)로 온다

주차 모듈 샘플에서 확인한 것(F-52, 모듈 84개·항목 87건 녹화):

- 한 모듈에 **제목이 같은 항목이 둘씩** 있다(15쌍) → 같은 항목인지는 `canvas_item_id`로만 가린다
- 항목 `type`은 `ExternalTool` 75 · `Assignment` 7 · `Quiz` 4 · `Page` 1이고 `File`은 0건이다
- 모듈 `position`은 연속이 아니다(1주차가 position 17인 과목이 있다) → 저장하지 않는다
- 항목이 없는 모듈이 흔하다(84개 중 47개가 `items: []`)
- 학생이 여는 주소는 `html_url`이다. `url`은 API 주소라 열어도 JSON이다

공지 샘플에서 확인한 것(F-53, 공지 16건 녹화):

- 본문은 `message`에 **HTML**로 온다(길이 80–4,458자). 녹화 파일에는 본문·이름이 길이만 남아 있어
  (`<3710자>`) 샘플 본문은 우리가 쓴 글이다 — 모양만 녹화와 같다
- `posted_at`은 16건 모두 있었다. 예약 공지(`delayed_post_at`)는 1건이었다
- `attachments`는 16건 중 2건(JSON 파일 하나, 포스터 PNG 하나). 칸은 녹화 그대로다(`attachment`).
  `filename`은 주소용으로 바뀐 글자이고(`%EC%A0%84…png`) 사람이 읽는 이름은 `display_name`이다.
  `url`의 `verifier`는 지운 값 대신 가짜 값을 넣었다 — 그 주소로 토큰 없이 받는다(10/19 녹화)
- `is_section_specific`는 16건 모두 false였다. true면 분반 한정이라 화면에 내려주지 않는다
- `locked`(8건)는 댓글 잠금이라 우리와 상관없다. `user_name`은 쓰지 않는다(개인정보)
- 제목이 비슷한 공지가 섞인다("휴강 안내" / "휴강안내 (Class Cancellation Notice)")
"""

from typing import Any

CANVAS_USER_ID = 77001

USERS_SELF: dict[str, Any] = {
    "id": CANVAS_USER_ID,
    "name": "테스트 학생",
    "created_at": "2023-02-20T14:37:18+09:00",
    "sortable_name": "학생, 테스트",
    "short_name": "테스트 학생",
    "avatar_url": "https://lms.test/images/thumbnails/1/abcdefghijklmnopqrstuvwx",
    "locale": None,
    "effective_locale": "ko",
    "permissions": {
        "can_update_name": False,
        "can_update_avatar": True,
        "limit_parent_app_web_access": False,
    },
}

TERM: dict[str, Any] = {
    "id": 94,
    "name": "2026년 2학기",
    "start_at": "2026-08-24T15:00:00Z",
    "end_at": None,
    "created_at": "2026-08-03T01:19:50Z",
    "workflow_state": "active",
    "grading_period_group_id": None,
}


def course(
    canvas_id: int,
    name: str,
    *,
    role: str = "student",
    workflow_state: str = "available",
) -> dict[str, Any]:
    """녹화한 과목 한 건의 모양. 바꿀 것만 인자로 받는다."""
    return {
        "id": canvas_id,
        "name": name,
        "account_id": 5798,
        "uuid": "cOuRsEuUiD0000000000000000000000000000000",
        "start_at": "2026-08-24T15:00:00Z",
        "created_at": "2026-08-03T02:58:13Z",
        "course_code": name,
        "default_view": "feed",
        "root_account_id": 1,
        "enrollment_term_id": TERM["id"],
        "end_at": "2026-12-31T14:59:59Z",
        "public_syllabus": False,
        "storage_quota_mb": 2000,
        "term": TERM,
        "calendar": {"ics": "https://lms.test/feeds/calendars/course_x.ics"},
        "time_zone": "Asia/Seoul",
        "blueprint": False,
        "enrollments": [
            {
                "type": role,
                "role": "StudentEnrollment" if role == "student" else "TaEnrollment",
                "role_id": 11,
                "user_id": CANVAS_USER_ID,
                "enrollment_state": "active",
                "limit_privileges_to_course_section": False,
            }
        ],
        "hide_final_grades": False,
        "workflow_state": workflow_state,
        "course_format": "on_campus",
        "restrict_enrollments_to_course_dates": True,
    }


DATABASE = course(214023, "202620HY23525_데이터베이스")
MACHINE_LEARNING = course(216515, "202620HY23534_기계학습")
# 과목명 꼴이 다른 과목(계획서 링크를 만들 수 없다)
SEMINAR = course(219001, "대학원 세미나(비정규)")
# 조교로 들어간 과목과 아직 열지 않은 과목은 목록에서 뺀다
ASSISTING = course(219002, "202620HY23999_조교과목", role="ta")
UNPUBLISHED = course(219003, "202620HY23998_준비중", workflow_state="unpublished")

COURSES: list[dict[str, Any]] = [
    DATABASE,
    MACHINE_LEARNING,
    SEMINAR,
    ASSISTING,
    UNPUBLISHED,
]
MINE: list[dict[str, Any]] = [DATABASE, MACHINE_LEARNING, SEMINAR]


# ── 과제 (F-51) ─────────────────────────────────────────────────────────────
# 마감이 있고 아직 내지 않은 과제. 가장 흔한 모양이다
HOMEWORK: dict[str, Any] = {
    "id": 2811242,
    "due_at": "2026-10-20T14:59:59Z",  # 2026-10-20 23:59:59 KST
    "unlock_at": "2026-10-13T00:00:00Z",
    "lock_at": "2026-10-22T14:59:59Z",
    "points_possible": 0.0,
    "grading_type": "points",
    "assignment_group_id": 579630,
    "position": 1,
    "allowed_attempts": -1,
    "course_id": 214023,
    "name": "실습 2주차 결과 제출",
    "submission_types": ["online_upload"],
    "has_submitted_submissions": True,  # 과목 전체 기준이라 내 제출과 무관하다
    "is_quiz_assignment": False,
    "workflow_state": "published",
    "html_url": "https://lms.test/courses/214023/assignments/2811242",
    "published": True,
    "submission": {
        "id": 106325980,
        "assignment_id": 2811242,
        "user_id": CANVAS_USER_ID,
        "submitted_at": None,
        "workflow_state": "unsubmitted",
        "attempt": None,
        "score": None,
        "grade": None,
        "graded_at": None,
        "late": False,
        "missing": False,
        "submission_type": None,
        "excused": None,
        "seconds_late": 0,
        "cached_due_date": "2026-10-20T14:59:59Z",
    },
}

# `due_at`이 null이고 `lock_at`만 있는 과제(녹화 17건 중 5건). 마감은 lock_at으로 본다
LAB_REPORT: dict[str, Any] = {
    "id": 2811588,
    "due_at": None,
    "unlock_at": None,
    "lock_at": "2026-10-18T14:59:59Z",
    "points_possible": 0.0,
    "grading_type": "points",
    "assignment_group_id": 579630,
    "position": 2,
    "allowed_attempts": -1,
    "course_id": 214023,
    "name": "실습 3주차 결과 제출",
    "submission_types": ["online_upload"],
    "has_submitted_submissions": True,
    "is_quiz_assignment": False,
    "workflow_state": "published",
    "html_url": "https://lms.test/courses/214023/assignments/2811588",
    "published": True,
    "lock_info": {
        "lock_at": "2026-10-18T14:59:59Z",
        "can_view": True,
        "asset_string": "assignment_2811588",
    },
    "submission": {
        "id": 106325981,
        "assignment_id": 2811588,
        "user_id": CANVAS_USER_ID,
        "submitted_at": "2026-10-15T23:02:17Z",
        "workflow_state": "submitted",
        "attempt": 1,
        "score": None,
        "grade": None,
        "graded_at": None,
        "late": False,
        "missing": False,
        "submission_type": "online_upload",
        "excused": None,
        "seconds_late": 0,
        "cached_due_date": None,
    },
}

# 퀴즈는 자동 채점돼 바로 graded로 온다(녹화 17건 중 4건)
QUIZ: dict[str, Any] = {
    "id": 2799146,
    "quiz_id": 85791,
    "is_quiz_assignment": True,
    "due_at": "2026-10-11T14:59:00Z",
    "unlock_at": None,
    "lock_at": "2026-10-11T14:59:00Z",
    "points_possible": 3.0,
    "grading_type": "points",
    "assignment_group_id": 579631,
    "position": 3,
    "course_id": 216515,
    "name": "3주차 퀴즈",
    "submission_types": ["online_quiz"],
    "has_submitted_submissions": True,
    "workflow_state": "published",
    "html_url": "https://lms.test/courses/216515/assignments/2799146",
    "published": True,
    "submission": {
        "id": 106325982,
        "assignment_id": 2799146,
        "user_id": CANVAS_USER_ID,
        "submitted_at": "2026-10-09T08:40:14Z",
        "workflow_state": "graded",
        "attempt": 1,
        "score": None,
        "grade": None,
        "graded_at": "2026-10-09T08:40:20Z",
        "submission_type": "online_quiz",
        "late": False,
        "missing": False,
        "excused": None,
        "seconds_late": 0,
    },
}

# 아직 열지 않은 과제. 학생 화면에는 안 보이니 저장하지 않는다(녹화에는 없었다 — 과목에서 본 모양을 옮겼다)
DRAFT_ASSIGNMENT: dict[str, Any] = {
    "id": 2820001,
    "due_at": "2026-12-01T14:59:59Z",
    "lock_at": None,
    "points_possible": 10.0,
    "course_id": 214023,
    "name": "기말 과제(준비 중)",
    "submission_types": ["online_upload"],
    "is_quiz_assignment": False,
    "workflow_state": "unpublished",
    "html_url": "https://lms.test/courses/214023/assignments/2820001",
    "published": False,
    "submission": {
        "id": 106325983,
        "assignment_id": 2820001,
        "user_id": CANVAS_USER_ID,
        "submitted_at": None,
        "workflow_state": "unsubmitted",
    },
}

# 데이터베이스 과목(214023)의 과제 목록 응답
DB_ASSIGNMENTS: list[dict[str, Any]] = [HOMEWORK, LAB_REPORT, DRAFT_ASSIGNMENT]
# 기계학습 과목(216515)의 과제 목록 응답
ML_ASSIGNMENTS: list[dict[str, Any]] = [QUIZ]


# ── 주차 모듈·항목 (F-52) ───────────────────────────────────────────────────
def _item(
    item_id: int,
    title: str,
    kind: str = "ExternalTool",
    *,
    course: int = 214023,
    module: int = 2871837,
    content: int | None = None,
) -> dict[str, Any]:
    """녹화한 항목 모양 그대로. `url`은 API 주소라 학생이 열 수 없다(`html_url`을 쓴다)."""
    return {
        "id": item_id,
        "title": title,
        "position": 2,
        "indent": 0,
        "type": kind,
        "module_id": module,
        "html_url": f"https://lms.test/courses/{course}/modules/items/{item_id}",
        "url": f"https://lms.test/api/v1/courses/{course}/external_tools/sessionless_launch?id=138",
        "page_url": None,
        "external_url": f"https://lms.test/learningx/lti/lecture_attendance/items/view/{item_id}",
        "content_id": content,
        "new_tab": None,
        "published": None,
    }


def _module(
    module_id: int, name: str, items: list[dict[str, Any]], *, position: int = 17
) -> dict[str, Any]:
    return {
        "id": module_id,
        "name": name,
        "position": position,  # 연속이 아니다(1주차가 17인 과목이 있었다)
        "unlock_at": None,
        "require_sequential_progress": False,
        "published": None,
        "items_count": len(items),
        "items_url": f"https://lms.test/api/v1/courses/214023/modules/{module_id}/items",
        "state": "started",
        "completed_at": None,
        "items": items,
    }


# 데이터베이스 과목: 3주차에 제목이 같은 항목 둘(녹화 15쌍과 같은 모양), 4주차는 빈 모듈
DB_MODULES: list[dict[str, Any]] = [
    _module(
        2871837,
        "3주차",
        [
            _item(8569302, "3주차 강의", content=138),
            _item(8569303, "3주차 강의"),  # 제목이 같다 — ID로만 가린다
            _item(8569304, "3주차 퀴즈", "Quiz", content=85791),
        ],
    ),
    _module(2871840, "4주차 (개천절 대체휴일)", [], position=21),
]

# 기계학습 과목: 모듈 하나에 과제 항목 하나
ML_MODULES: list[dict[str, Any]] = [
    _module(
        2756894,
        "Week 3 : Trees",
        [
            _item(
                8631787,
                "3주차 과제 안내",
                "Assignment",
                course=216515,
                module=2756894,
                content=2799146,
            )
        ],
        position=1,
    )
]

# `include[]=items`로 항목이 오지 않은 모듈(녹화에는 없었지만 Canvas 문서에 있는 경우)
MODULE_WITHOUT_ITEMS: dict[str, Any] = {
    "id": 2871999,
    "name": "5주차",
    "position": 25,
    "items_count": 1,
    "items_url": "https://lms.test/api/v1/courses/214023/modules/2871999/items",
    "state": "locked",
}


# ── 과목 공지 (F-53) ────────────────────────────────────────────────────────
# `GET /courses/{id}/discussion_topics?only_announcements=true` 응답 모양이다.
# 본문(message)은 우리가 쓴 글이고, 나머지 칸은 녹화와 같은 모양·값 꼴이다.
RESEARCH_TOPIC_ID = 520964
CANCELLED_TOPIC_ID = 520357
MATERIAL_TOPIC_ID = 519515
SECTION_TOPIC_ID = 521001
DELAYED_TOPIC_ID = 521002
RESEARCH_TITLE = "데이터베이스 연구실 연구 참여 학생 모집"
RESEARCH_BODY = (
    "<p>데이터베이스 연구실에서 2026학년도 겨울 연구 참여 학생을 모집합니다.</p>"
    "<ul><li>모집 인원: 2명</li>"
    "<li>지원 자격: 3학년 이상, 전체 평점 3.0 이상</li>"
    "<li>활동 기간: 12월 ~ 2월 (주 10시간)</li>"
    "<li>제출 서류: 성적증명서, 자기소개서</li>"
    "<li>신청 마감: 11월 20일 18시</li></ul>"
    "<p>문의는 연구실로 주세요.</p>"
)


GUIDE_FILE_ID = 11637886  # 녹화한 JSON 첨부(공지 "3주차 강의에 사용되었던 json 파일")
POSTER_FILE_ID = 11592089  # 녹화한 PNG 첨부(전공 DAY 포스터)


def attachment(
    file_id: int = GUIDE_FILE_ID,
    *,
    display_name: str = "ERICA-projects-guide-v2.json",
    filename: str | None = None,
    content_type: str = "application/json",
    size: int | None = 86169,
    base: str = "https://lms.test",
) -> dict[str, Any]:
    """공지 첨부 한 건(10/16 녹화의 칸 그대로). 주소의 verifier는 가짜 값이다."""
    return {
        "id": file_id,
        "uuid": "u" * 40,
        "folder_id": 2366964,
        "display_name": display_name,
        "filename": filename if filename is not None else display_name,
        "upload_status": "success",
        "content-type": content_type,
        "url": f"{base}/files/{file_id}/download?download_frd=1&verifier=v{file_id}abc",
        "size": size,
        "created_at": "2026-09-21T05:06:22Z",
        "updated_at": "2026-09-21T05:06:22Z",
        "unlock_at": None,
        "locked": False,
        "hidden": False,
        "lock_at": None,
        "hidden_for_user": False,
        "thumbnail_url": None,
        "modified_at": "2026-09-21T05:06:22Z",
        "mime_class": "file",
        "media_entry_id": None,
        "locked_for_user": False,
    }


POSTER_ATTACHMENT: dict[str, Any] = attachment(
    POSTER_FILE_ID,
    display_name="전공DAY 포스터.png",
    filename="%EC%A0%84%EA%B3%B5DAY+%ED%8F%AC%EC%8A%A4%ED%84%B0.png",
    content_type="image/png",
    size=979532,
)


def announcement(
    topic_id: int,
    course_id: int,
    title: str,
    *,
    message: str,
    posted_at: str | None = "2026-09-28T04:43:23Z",
    attachments: list[dict[str, Any]] | None = None,
    section_specific: bool = False,
) -> dict[str, Any]:
    """공지 한 건. 칸 이름·꼴은 녹화 그대로다."""
    url = f"https://lms.test/courses/{course_id}/discussion_topics/{topic_id}"
    return {
        "id": topic_id,
        "title": title,
        "message": message,
        "posted_at": posted_at,
        "created_at": posted_at or "2026-09-28T04:43:23Z",
        "delayed_post_at": None if posted_at else "2026-12-01T00:00:00Z",
        "last_reply_at": posted_at,
        "lock_at": None,
        "assignment_id": None,
        "root_topic_id": None,
        "position": 1,
        "discussion_type": "side_comment",
        "is_section_specific": section_specific,
        "user_name": "담당 교수",
        "permissions": {"attach": False, "update": False, "reply": False, "delete": False},
        "read_state": "unread",
        "unread_count": 0,
        "attachments": list(attachments or []),
        "published": True,
        "locked": True,
        "html_url": url,
        "url": url,
        "pinned": False,
        "todo_date": None,
    }


DB_ANNOUNCEMENTS: list[dict[str, Any]] = [
    announcement(
        RESEARCH_TOPIC_ID,
        214023,
        RESEARCH_TITLE,
        message=RESEARCH_BODY,
        posted_at="2026-10-14T04:41:13Z",
    ),
    announcement(
        CANCELLED_TOPIC_ID,
        214023,
        "휴강 안내",
        message="<p>10월 20일(월) 수업은 휴강합니다. 보강은 추후 공지합니다.</p>",
        posted_at="2026-10-10T10:00:03Z",
    ),
    announcement(
        MATERIAL_TOPIC_ID,
        214023,
        "3주차 강의에 사용한 json 파일",
        message="<p>수업에서 쓴 파일을 첨부합니다.</p>",
        posted_at="2026-10-05T05:06:22Z",
        attachments=[attachment()],
    ),
]
ML_ANNOUNCEMENTS: list[dict[str, Any]] = [
    announcement(
        519001,
        216515,
        "중간고사 안내",
        message="<p>중간고사는 수업 시간에 봅니다. 범위는 1~6주차입니다.</p>",
        posted_at="2026-10-12T01:00:00Z",
    )
]


# ── 주차학습 강의 (11/24) ───────────────────────────────────────────────────
# 2026-11-12 한양대 실측(학생 본인 계정, 읽기만)의 **모양**이다. 값(번호·제목·시각)은 지어냈다.
# 과목 탭 → 한 번 쓰는 실행 주소 → LTI 폼 → `xn_api_token` 쿠키 → 주차학습 목록(`include_detail=true`)
TABS: list[dict[str, Any]] = [
    {"id": "home", "label": "홈", "type": "internal", "position": 1, "html_url": "/courses/214023"},
    # 옮기기 전 도구가 탭에 남아 있었다. 지금 도구('주차학습')를 고른다
    {
        "id": "context_external_tool_138",
        "label": "(구) 강의콘텐츠",
        "type": "external",
        "position": 2,
        "html_url": "/courses/214023/external_tools/138",
    },
    {
        "id": "context_external_tool_140",
        "label": "주차학습",
        "type": "external",
        "position": 3,
        "html_url": "/courses/214023/external_tools/140",
    },
    {"id": "assignments", "label": "과제", "type": "internal", "position": 4},
]
TABS_WITHOUT_WEEKLY: list[dict[str, Any]] = [TABS[0], TABS[3]]
LAUNCH_VERIFIER = "verifier-sample-0000"  # 한 번 쓰는 실행 주소의 값(지어냄). 로그에 남으면 안 된다
LAUNCH: dict[str, Any] = {
    "id": 140,
    "name": "주차학습",
    "url": (
        "https://lms.test/courses/214023/external_tools/sessionless_launch"
        f"?verifier={LAUNCH_VERIFIER}&id=140&launch_type=course_navigation"
    ),
}
LEARNINGX_TOKEN = "xn-sample-token-0000"  # 주차학습이 쿠키로 주는 표(지어냄)


def launch_page(action: str = "https://lms.test/learningx/lti/modulebuilder") -> str:
    """Canvas가 주는 실행 페이지: 숨은 값을 담은 POST 폼 하나와 그 폼을 바로 보내는 스크립트(실측 값 47개를 줄였다)."""
    return f"""<!DOCTYPE html><html><head><title>주차학습</title></head><body>
<form action="{action}" method="POST" id="tool_form" target="_self">
  <input type="hidden" name="oauth_consumer_key" value="learningx" />
  <input type="hidden" name="custom_canvas_course_id" value="214023" />
  <input type="hidden" name="lis_person_name_full" value="학생" />
  <input type="hidden" name="oauth_signature" value="c2ln&amp;=" />
  <button type="submit">계속</button>
</form>
<form id="logout" method="get" action="/logout"><input type="hidden" name="x" value="1" /></form>
<script>document.getElementById("tool_form").submit()</script>
</body></html>"""


# 폼이 보내는 값(HTML 글자를 풀어 둔 것). 클라이언트가 이대로 다시 보내야 한다
LAUNCH_FIELDS: list[tuple[str, str]] = [
    ("oauth_consumer_key", "learningx"),
    ("custom_canvas_course_id", "214023"),
    ("lis_person_name_full", "학생"),
    ("oauth_signature", "c2ln&="),
]


def lecture_item(
    module_item_id: int | None,
    title: str,
    *,
    content_type: str = "attendance_item",
    media: str | None = "movie",
    live: bool = False,
    use_attendance: bool = True,
    completed: Any = False,
    determinable: bool = True,
    attendance: str = "none",
    period: str | None = "open",
    unlock_at: str | None = None,
    due_at: str | None = None,
    late_at: str | None = None,
    duration: Any = None,
    published: bool = True,
    item_id: int | None = None,
) -> dict[str, Any]:
    """주차학습 항목 하나(실측 모양). 학생 본인의 상태가 `completed`·`attendance_status`로 함께 온다."""
    content: dict[str, Any] = {"content_type": media} if media else {}
    if duration is not None:
        content["duration"] = duration
    data: dict[str, Any] = {
        "item_id": item_id if item_id is not None else (module_item_id or 0) + 1_000_000,
        "title": title,
        "published": published,
        "use_attendance": use_attendance,
        "lecture_period_status": period,
        "unlock_at": unlock_at,
        "due_at": due_at,
        "late_at": late_at,
        "item_content_data": content,
    }
    if live:
        data["item_content_type"] = "video_conference"
    return {
        "module_item_id": module_item_id,
        "title": title,
        "content_type": content_type,
        "published": published,
        "completed": completed,
        "completion_determinable": determinable,
        "attendance_status": attendance,
        "content_data": data,
    }


# 데이터베이스(214023) — 2026-10-16 12:00 KST 기준으로 다 들음·안 들음·놓침·학습자료·열리기 전이 하나씩.
# 출석 대상이 아닌 PDF, 퀴즈, 공개하지 않은 강의는 강의가 아니다
DB_LECTURE_MODULES: list[dict[str, Any]] = [
    {
        "module_id": 9003,
        "title": "3주차",
        "module_items": [
            lecture_item(
                8569302,
                "3주차 강의",
                completed=True,
                attendance="attendance",
                period="closed",
                unlock_at="2026-09-15T00:00:00Z",
                due_at="2026-09-21T14:59:59Z",
                duration=1932.4,
            ),
            # 제목이 같은 둘째 항목은 출석 대상이 아닌 PDF다
            lecture_item(8569303, "3주차 강의", media="pdf", use_attendance=False),
            lecture_item(8569304, "3주차 퀴즈", content_type="quiz", media=None),
        ],
    },
    {"module_id": 9004, "title": "4주차 (개천절 대체휴일)", "module_items": []},
    {
        "module_id": 9006,
        "title": "6주차",
        "module_items": [
            lecture_item(
                8570001,
                "6주차 강의 1부",
                media="mp4",
                unlock_at="2026-10-13T00:00:00Z",
                due_at="2026-10-19T14:59:59Z",
                late_at="2026-10-26T14:59:59Z",
                duration=2405,
            ),
            lecture_item(
                8570002,
                "6주차 실시간 수업",
                media=None,
                live=True,
                attendance="absent",
                period="closed",
                due_at="2026-10-14T06:00:00Z",
            ),
            lecture_item(
                8570003,
                "6주차 읽기 자료",
                media="pdf",
                completed=True,
                attendance="attendance",
            ),
            lecture_item(8570004, "6주차 보충 강의(준비 중)", published=False),
        ],
    },
    {
        "module_id": 9007,
        "title": "7주차",
        "module_items": [
            lecture_item(
                8570005,
                "7주차 강의",
                period="not_open",
                unlock_at="2026-10-20T00:00:00Z",
                due_at="2026-10-26T14:59:59Z",
            )
        ],
    },
]

# 기계학습(216515) — Canvas 주차 항목 번호가 없는 강의(LearningX 번호로 가린다)와 완료 여부를 알 수 없는 강의,
# 지각 인정 기간인 강의
ML_LECTURE_MODULES: list[dict[str, Any]] = [
    {
        "module_id": 9101,
        "title": "Week 3 : Trees",
        "module_items": [
            lecture_item(
                None,
                "Decision trees (recorded)",
                item_id=71001,
                determinable=False,
            ),
            lecture_item(
                8631790,
                "Week 3 lecture",
                period="late",
                due_at="2026-10-15T14:59:59Z",
                late_at="2026-10-22T14:59:59Z",
            ),
        ],
    }
]
