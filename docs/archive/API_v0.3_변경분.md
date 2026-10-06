# API 명세 v0.3 변경분 — 디자인 초안 대조 반영

> 📝 기준: API 명세 v0.2 → v0.3 · 2026-10-05 · 기준 문서: PRD v0.8, ERD v0.8
>
> 엔드포인트 6개를 더하고 기존 8곳의 요청·응답을 바꾼다. 예시는 v0.2 형식에서 새 필드만 보이도록 줄였다. Figma Make 시안의 `src/types/api.ts`가 이 문서와 같은 필드 이름을 쓴다.

---

## 3장 엔드포인트 한눈에 보기 (추가 행)

| 분류 | 메서드 · 경로 | 설명 | 기능 | 우선 |
| --- | --- | --- | --- | --- |
| 내 정보 | `POST /me/consents` | 약관·개인정보 동의 기록 | F-02 | P0 |
| 내 정보 | `GET /me/settings` · `PATCH /me/settings` | 알림·LMS 과제 자동 등록 설정 | F-06 | P1 |
| 알림 | `GET /notifications` | 알림함 목록과 안 읽은 수 | F-35 | P0 |
| 알림 | `POST /notifications/read` | 읽음 처리(선택 또는 전체) | F-35 | P0 |
| LMS | `GET /lms/courses/{id}` | 과목 상세: 과제·주차 자료·공지·계획서·내 자료, 열람 기록 | F-14, F-15, F-51–F-53 | P0 |

---

## 4장 인증 · 내 정보

### `GET /me` (필드 추가)

```json
{
  "...": "v0.2 필드 그대로",
  "consented": true,
  "unread_notifications": 3
}
```

- `consented`: 약관·개인정보 동의를 마쳤는지. false면 프론트가 온보딩 동의 단계로 보낸다
- `unread_notifications`: 헤더 알림 배지 숫자

### `POST /me/consents` (신설)

```json
// Request
{ "consent_version": "2026-10-05", "agree_terms": true, "agree_privacy": true }

// Response 200
{ "terms_agreed_at": "2026-10-05T17:20:00+09:00", "privacy_agreed_at": "2026-10-05T17:20:00+09:00", "consent_version": "2026-10-05" }
```

- 둘 중 하나라도 false면 `422 VALIDATION_FAILED`
- 동의 전에는 `/me/profile` 수정과 공고·플래너 API가 `403 CONSENT_REQUIRED`를 돌려준다

### `GET /me/settings` · `PATCH /me/settings` (신설, P1)

```json
{ "push_enabled": true, "muted_notification_types": ["new_material"], "calendar_auto_lms": true }
```

- `PATCH`는 보낸 필드만 바꾸고, 행이 없으면 기본값으로 만든다
- `calendar_auto_lms`를 끄면 이후 새 과제만 캘린더에 넣지 않는다. 이미 등록한 일정은 지우지 않는다

---

## 5장 공고 피드 · 상세

### `GET /opportunities` (변경)

- `eligibility`는 쉼표로 여러 값을 받는다. 홈은 기본 목록을 `eligibility=eligible,undetermined`로 부르고, "지원 어려움 N개" 묶음을 펼칠 때 `eligibility=ineligible`로 따로 부른다
- `sort=deadline`은 마감일 없는 공고를 맨 뒤로 보낸다
- 아이템에 `easy_summary`(카드 설명 한 줄), `is_new`, `eligibility.display_status`(`eligible` · `missing_info` · `needs_review` · `ineligible`)를 더한다
- `counts`는 카테고리 필터와 상관없이 전체 기준이다(ERD 집계 쿼리)

```json
{
  "items": [
    {
      "...": "v0.2 필드 그대로",
      "easy_summary": "직전학기 성적이 좋은 학생에게 등록금 일부를 감면해 줘요.",
      "is_new": true,
      "eligibility": {
        "status": "undetermined",
        "display_status": "missing_info",
        "summary": "직전학기 취득학점을 입력하면 판정할 수 있어요",
        "missing_fields": ["credits_last_semester"]
      }
    }
  ],
  "next_cursor": null,
  "counts": {
    "eligible": 8, "new_eligible": 2,
    "undetermined": 3, "missing_info": 2, "needs_review": 1,
    "ineligible": 9,
    "deadline_soon": 2
  }
}
```

### `GET /opportunities/{id}` (변경)

```json
{
  "...": "v0.2 필드 그대로",
  "course_name": null,
  "poster_url": null,
  "eligibility": {
    "status": "eligible",
    "display_status": "eligible",
    "missing_fields": [],
    "conditions": [
      {
        "requirement_id": "uuid",
        "field": "credits_last_semester",
        "label": "직전학기 취득학점",
        "condition_text": "직전학기 12학점 이상",
        "user_value_text": "18학점",
        "outcome": "pass",
        "evidence_text": "직전학기 12학점 이상 취득한 재학생",
        "is_ambiguous": false
      }
    ]
  },
  "documents": [
    { "id": "uuid", "name": "재학증명서", "issuer": "HY-in", "lead_days": 0, "effort_minutes": null, "form_url": null, "task_id": "uuid", "is_done": true },
    { "id": "uuid", "name": "장학금 신청서", "issuer": "공고 첨부파일", "lead_days": 0, "effort_minutes": 30, "form_url": "https://...", "task_id": "uuid", "is_done": false }
  ],
  "process": {
    "extraction": [
      { "seq": 1, "label": "공고 원문 읽기", "status": "succeeded", "latency_ms": 2100 },
      { "seq": 2, "label": "지원 자격 정리", "status": "succeeded", "latency_ms": 2340 }
    ],
    "evaluated_at": "2026-10-05T09:12:00+09:00",
    "prepare_run_id": null
  }
}
```

- `condition_text`·`user_value_text`는 백엔드가 field·operator·value로 만든 화면용 문구다. 미입력이면 `user_value_text`는 null
- `missing_fields`는 정보 입력창(F-03)에 띄울 항목이다
- 서류의 `task_id`·`is_done`은 준비하기 전에는 null이고, 체크는 기존 `PATCH /planner/tasks/{task_id}`로 한다
- `poster_url`은 포스터 공고의 원본 이미지(Storage 서명 URL, 1시간), `course_name`은 과목 공지에서 온 공고의 과목명이다
- `process.extraction`은 추출 실행에서 라벨·상태·소요 시간만 뽑은 것이라 배치 실행이나 남의 포스터도 내려준다. `GET /runs/{id}`의 본인 실행 제한은 그대로 둔다
- 이 API를 부르면 `opportunity_views`를 upsert한다(`first_viewed_at` 유지, `last_viewed_at` 갱신)

---

## 6장 업로드 · 포스터

### `POST /files` (변경)

- `kind=poster`일 때 기존 이미지 형식(jpg·png·webp·heic)에 더해 2쪽 이하 PDF를 받는다. 3쪽 이상이면 `413 PAGE_LIMIT_EXCEEDED`
- 업로드한 파일 이름을 `files.original_name`에 저장한다

### `POST /posters/extract` 결과 (변경)

`draft.requirements[]`에 `condition_text`를, `draft.documents[]`에 `effort_minutes`·`form_url`을 더한다. 확인 화면은 요건을 문장으로 보여주고 행 단위로 지울 수 있다.

```json
{
  "kind": "poster_extract",
  "draft": {
    "...": "v0.2 필드 그대로",
    "requirements": [
      { "field": "enrollment_status", "operator": "in", "value": ["enrolled", "on_leave"], "condition_text": "재학생 또는 휴학생", "evidence_text": "국내 대학 재학생 및 휴학생", "is_ambiguous": false }
    ],
    "documents": [ { "name": "참가신청서", "issuer": "주최측 홈페이지", "lead_days": 2, "effort_minutes": 60, "form_url": null } ]
  },
  "duplicate_candidate": null
}
```

---

## 7장 준비하기 · 플래너 · 캘린더

### `GET /planner/tasks` (변경)

```json
{
  "items": [
    {
      "id": "uuid", "title": "재학증명서 발급", "due_date": "2026-10-05", "is_done": false, "source": "prep_plan",
      "link": { "type": "opportunity", "id": "uuid", "title": "한양 브레인 보완 장학금", "category": "scholarship" }
    }
  ],
  "markers": [
    { "kind": "deadline", "date": "2026-10-10", "title": "한양 브레인 보완 장학금 마감", "opportunity_id": "uuid", "category": "scholarship" }
  ]
}
```

- `markers`는 체크할 수 없는 표시 항목이다. 지금은 준비 중인 공고의 마감일(`kind = deadline`)만 있다
- `link.category`는 공고에서 온 할 일에만 있고, LMS·강의계획서 할 일은 칩에 과목명(`link.title`)을 쓴다
- LMS 과제의 `is_done`은 사용자가 바꿀 수 있고, 동기화는 미제출에서 제출로 바뀔 때만 true로 바꾼다

---

## 9장 LMS 연동

### `GET /lms/courses` (변경)

아이템에 두 필드를 더한다. `next_due`는 미제출 과제와 확정된 강의계획서 일정 중 가장 가까운 것이고, 없으면 null이다.

```json
{ "new_materials": 2, "next_due": { "kind": "assignment", "title": "Quiz 3", "due_at": "2026-10-11T23:59:00+09:00" } }
```

### `GET /lms/courses/{id}` (신설)

```json
{
  "course": { "id": "uuid", "short_name": "선형대수", "has_syllabus": true, "portal_syllabus_url": "https://portal.hanyang.ac.kr/..." },
  "assignments": [ { "id": "uuid", "title": "Homework 4", "due_at": "2026-10-13T23:59:00+09:00", "submission_state": "unsubmitted", "html_url": "https://learning.hanyang.ac.kr/..." } ],
  "module_items": [ { "id": "uuid", "module_name": "8주차", "title": "08 - Eigenvalues", "html_url": "https://learning.hanyang.ac.kr/...", "is_new": true, "uploaded_file_id": null } ],
  "announcements": [ { "id": "uuid", "title": "강의실 변경 안내", "summary": "다음 주 수업은 다른 강의실에서 한다", "category": "schedule_change", "posted_at": "2026-10-04T14:00:00+09:00", "opportunity_id": null } ],
  "syllabus_items": [ { "id": "uuid", "item_type": "midterm", "title": "중간고사", "starts_at": "2026-10-20T10:30:00+09:00", "is_confirmed": true } ],
  "materials": [ { "file_id": "uuid", "original_name": "08_eigen.pdf", "status": "succeeded" } ]
}
```

- 부르면 그 과목의 `last_viewed_at`을 지금으로 바꾼다. `is_new`는 바꾸기 전 값으로 계산한다

### `GET /lms/updates` (변경)

- `type`에 `assignment`(새 과제, 마감 D-3 이내 미제출 과제)를 더한다
- announcement 아이템에 `summary`를 더한다

---

## 10장 알림

### `GET /notifications` (신설)

`?unread_only=false&limit=20&cursor=...`

```json
{
  "items": [
    {
      "id": "uuid", "type": "deadline_soon",
      "title": "장학금 마감이 가까워요", "body": "한양 브레인 보완 장학금 · D-3",
      "scheduled_at": "2026-10-05T09:00:00+09:00", "read_at": null,
      "link": { "type": "opportunity", "id": "uuid" }
    },
    {
      "id": "uuid", "type": "profile_needed",
      "title": "프로필 정보가 필요해요", "body": "경기도 청년 역량개발 지원사업 · 거주지역을 입력하면 판정할 수 있어요",
      "scheduled_at": "2026-10-05T08:00:00+09:00", "read_at": null,
      "link": { "type": "opportunity", "id": "uuid", "focus": "profile_input" }
    }
  ],
  "unread_count": 3,
  "next_cursor": null
}
```

- `scheduled_at`이 지난 알림만 최신순으로 내려준다
- `link.type`은 `opportunity` · `planner_task` · `lms_assignment` · `lms_module_item` · `lms_announcement`이고, `focus: profile_input`이면 상세에서 정보 입력창을 바로 연다
- 푸시 페이로드의 `type`에도 `profile_needed`를 더한다

### `POST /notifications/read` (신설)

```json
// Request: 둘 중 하나
{ "ids": ["uuid", "uuid"] }
{ "all": true }

// Response 200
{ "unread_count": 0 }
```

---

## 13장 에러 코드 (추가 행)

| 코드 | HTTP | 의미 | 프론트 처리 |
| --- | --- | --- | --- |
| `CONSENT_REQUIRED` | 403 | 약관·개인정보 동의 전 | 온보딩 동의 단계로 이동 |
