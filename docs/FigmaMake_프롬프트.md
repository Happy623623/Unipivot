# Figma Make 작업 가이드 — 디자인 v0.8 반영

> 📝 기준: PRD v0.8 · ERD v0.8 · API 명세 v0.3 변경분 · 2026-10-05
>
> 대상: Figma Make 프로젝트 "Upload_Poster_Feature"(React 19 + Vite + Tailwind v4)

Figma Make로 디자인 수정 요청(P0 10곳, 표기 7곳)을 반영한다. 화면을 고치는 동시에 코드를 API 명세와 같은 타입·목데이터 구조로 정리해, Next.js로 옮길 때 `src/api/client.ts` 안만 실제 호출로 바꾸면 되게 만든다.

## 쓰는 법

1. Make의 코드 보기에서 `AGENTS.md`를 함께 받은 `AGENTS.md`로 통째로 바꾼다. 앞부분은 원래 내용 그대로이고 뒤에 프로젝트 규칙을 붙였다. `CLAUDE.md`가 이 파일을 불러오므로 Make의 AI가 프롬프트마다 화면 구성·판정 라벨·데이터 규칙을 참고한다.
2. 아래 프롬프트를 0번부터 하나씩 붙여 넣는다. 뒤 프롬프트가 앞에서 만든 타입·목데이터·상태 미리보기를 쓴다.
3. 프롬프트마다 "확인할 것"을 미리보기에서 보고 틀린 부분만 짧게 다시 요청한다. 크게 틀어지면 이전 버전으로 되돌린 뒤 프롬프트를 둘로 나눠 넣는다.
4. 단계가 끝나면 Make 파일 링크(figma.com/make/…)를 공유한다. Figma 연결로 Make 파일의 최신 코드를 바로 읽어 PRD·API와 대조한다. zip을 다시 올릴 필요가 없다.
5. Next.js로 옮길 때는 `src/components`·`src/screens`·`src/types`·`src/lib`를 가져가고 `src/api/client.ts` 함수 안만 실제 API 호출로 바꾼다. `src/dev/`는 버린다.

## 프롬프트 순서

| 순서 | 프롬프트 | 반영하는 수정 요청 | 기능 |
| --- | --- | --- | --- |
| 0 | 구조 정리와 타입 | 기반 작업(화면 변화 없음) | — |
| 1 | 목데이터와 상태 미리보기 | 기반 작업 | — |
| 2 | 표기와 라벨 | 표기·문구 7곳 | F-40, F-41 |
| 3 | 홈 | 요약 카드 필터, 지원 어려움 하단 묶음, 상시 | F-40 |
| 4 | 공고 상세 상태별 화면 | 상태별 화면, 정보 입력, 원문 보기·신고 | F-03, F-13, F-17, F-22, F-25 |
| 5 | 준비하기 | 준비하기 흐름, 서류 체크–플래너 연동 | F-30–F-32, F-42 |
| 6 | 포스터 등록 | 분석·실패·중복·공개 안내·요건 목록·촬영 | F-13, F-16 |
| 7 | 학업과 LMS 연결 | 과목 카드, 학업 피드, 토큰 연결 | F-50–F-53 |
| 8 | 과목 상세 | 과제·자료·공지·계획서 탭, 요약·구간 번역 | F-14, F-15, F-51, F-52 |
| 9 | 플래너 | 일정 추가, 마감 표시, 날짜 선택 | F-43 |
| 10 | 알림 패널 | 읽음 처리, 화면 이동, 종 버튼 | F-35 |
| 11 | 설정 | 연결 해제, 탈퇴, 알림 설정 | F-06, F-50 |
| 12 | 로그인·온보딩 | 로그인, 동의, 프로필 4단계 | F-01, F-02 |
| 13 | 다듬기 (P1) | 아이콘, 빈 상태, 모바일 주간 플래너 | — |
| 14 | 남은 화면 (P1) | 대체 공고, 문서함, 알림 전체 보기, .ics | F-23, F-44, F-35, F-34 |

---

## 프롬프트 0 · 구조 정리와 타입

````text
지금 화면 모양은 그대로 두고 코드 구조만 정리해줘.

1. App.tsx를 나눠줘. 공통 조각은 src/components/(Badge, Button, Header, Sidebar, AppShell), 화면은 src/screens/(Home, OpportunityDetail, Planner, PosterUpload, Academics)로. 지금 화면 안에 있는 예시 데이터는 이번엔 그대로 둬.
2. 라우팅은 지금처럼 상태 기반으로 두고 Route 타입을 다음으로 바꿔줘.
   { name: "home" } | { name: "opportunity"; id: string; focus?: "profile_input" } | { name: "planner" } | { name: "academics" } | { name: "course"; id: string; tab?: "assignments" | "materials" | "announcements" | "syllabus" } | { name: "upload" } | { name: "settings" } | { name: "onboarding" }
3. 아래 코드를 src/types/api.ts로 그대로 만들어줘. 필드 이름은 바꾸지 마.
4. src/lib/format.ts에 KST 날짜 포맷("10월 5일 월요일", "10/7"), D-day 문자열("D-3", 당일 "D-day", 마감일이 없으면 "상시"), 카테고리 한글 이름 함수를 만들어줘.

```ts
// API 명세 v0.3과 1:1로 맞춘 타입. 필드 이름을 바꾸지 않는다.
// 일시는 ISO 8601 문자열(+09:00), 날짜만은 "YYYY-MM-DD".

export type Category = "scholarship" | "school_program" | "youth_policy" | "contest" | "activity" | "research" | "exam" | "etc";
export type SourceType = "school_notice" | "youth_policy" | "contest" | "poster" | "lms_announcement";
export type EligibilityStatus = "eligible" | "undetermined" | "ineligible";
export type DisplayStatus = "eligible" | "missing_info" | "needs_review" | "ineligible";
export type RunStatus = "pending" | "running" | "succeeded" | "failed";
export type NotificationType =
  | "new_eligible" | "new_assignment" | "new_material" | "schedule_change"
  | "task_due" | "deadline_soon" | "profile_needed";

// GET /me
export interface Me {
  user_id: string;
  display_name: string;
  hyin_verified: boolean;
  calendar_connected: boolean;
  lms: { status: "active" | "error" | "disconnected"; last_synced_at: string | null } | null;
  profile_completion: { filled: number; total: number };
  consented: boolean;
  unread_notifications: number;
}

// GET /me/profile (모든 값 null 가능)
export interface Profile {
  department: string | null;
  grade: number | null;
  enrollment_status: "enrolled" | "on_leave" | "deferred_graduation" | "graduated" | null;
  semesters_completed: number | null;
  credits_total: number | null;
  credits_last_semester: number | null;
  gpa_total: number | null;
  gpa_last_semester: number | null;      // 직전학기 장학용 평점(F 포함)
  gpa_scale: number;                     // 기본 4.5
  birth_date: string | null;
  military_service_months: number | null;
  region_sido: string | null;
  region_sigungu: string | null;
  income_bracket: number | null;         // 학자금 지원구간
  median_income_pct: number | null;      // 기준 중위소득 %
  welfare_status: "none" | "near_poverty" | "basic_livelihood" | null;
}

// GET /me/settings
export interface Settings {
  push_enabled: boolean;
  muted_notification_types: NotificationType[];
  calendar_auto_lms: boolean;
}

// GET /opportunities
export interface FeedEligibility {
  status: EligibilityStatus;
  display_status: DisplayStatus;
  summary: string;                       // 카드의 상태 사유 한 줄
  missing_fields: string[];
}
export interface OpportunityItem {
  id: string;
  title: string;
  organizer: string | null;
  category: Category;
  source_type: SourceType;
  deadline_at: string | null;
  d_day: number | null;
  easy_summary: string | null;
  eligibility: FeedEligibility;
  recommend_reason: string | null;       // P1
  needs_review: boolean;
  uploader_masked: string | null;        // 포스터 공고만, 예: "김*지"
  course_name: string | null;            // 과목 공지에서 온 공고만
  prepared: boolean;
  is_new: boolean;
}
export interface FeedCounts {
  eligible: number; new_eligible: number;
  undetermined: number; missing_info: number; needs_review: number;
  ineligible: number; deadline_soon: number;
}
export interface FeedResponse { items: OpportunityItem[]; next_cursor: string | null; counts: FeedCounts; }

// GET /opportunities/{id}
export interface Condition {
  requirement_id: string;
  field: string;
  label: string;                         // "직전학기 취득학점"
  operator: string;
  value: unknown;
  user_value: unknown;
  condition_text: string;                // "직전학기 12학점 이상"
  user_value_text: string | null;        // "18학점", 미입력이면 null
  outcome: "pass" | "fail" | "unknown";
  evidence_text: string | null;          // 근거 원문 문장
  is_ambiguous: boolean;
}
export interface DocumentItem {
  id: string;
  name: string;
  issuer: string | null;
  how_to: string | null;
  lead_days: number | null;              // 0이면 즉시 발급
  effort_minutes: number | null;         // 작성 예상 시간
  form_url: string | null;               // 첨부 양식
  is_required: boolean;
  task_id: string | null;                // 준비하기 전에는 null
  is_done: boolean | null;
}
export interface ProcessStep { seq: number; label: string; status: RunStatus; latency_ms: number | null; }
export interface OpportunityDetail {
  id: string;
  title: string;
  organizer: string | null;
  category: Category;
  source_type: SourceType;
  original_url: string | null;
  poster_url: string | null;             // 포스터 공고의 원본 이미지
  easy_summary: string | null;
  apply_start_at: string | null;
  deadline_at: string | null;
  needs_review: boolean;
  extraction_confidence: number | null;
  uploader_masked: string | null;
  course_name: string | null;
  eligibility: {
    status: EligibilityStatus;
    display_status: DisplayStatus;
    reason_text: string | null;          // 탈락 사유
    missing_fields: string[];
    conditions: Condition[];
    evaluated_at: string;
  };
  documents: DocumentItem[];
  prep: {
    prepared: boolean;
    prep_plan_id: string | null;
    tasks_total: number;
    tasks_done: number;
    calendar_events: { id: string; provider: "google" | "ics" }[];
  };
  process: { extraction: ProcessStep[]; evaluated_at: string; prepare_run_id: string | null };
  reported_by_me: boolean;
}

// GET /runs/{id}: 포스터 추출·준비하기 진행 표시
export interface Run<R = unknown> {
  id: string;
  status: RunStatus;
  steps: { seq: number; tool: string; label: string; status: RunStatus; latency_ms: number | null }[];
  result: R | null;
  error: { code: string; message: string } | null;
}
export interface PosterExtractResult {
  kind: "poster_extract";
  draft: {
    title: string;
    organizer: string | null;
    category: Category;
    apply_start_at: string | null;
    deadline_at: string | null;
    easy_summary: string | null;
    requirements: { field: string; operator: string; value: unknown; condition_text: string; evidence_text: string | null; is_ambiguous: boolean }[];
    documents: { name: string; issuer: string | null; lead_days: number | null; effort_minutes: number | null; form_url: string | null }[];
    extraction_confidence: number;
    low_confidence_fields: string[];
  };
  duplicate_candidate: { opportunity_id: string; title: string } | null;
}
export interface PrepareResult {
  kind: "prepare";
  prep_plan_id: string;
  documents: DocumentItem[];
  tasks: { id: string; title: string; due_date: string; document_id: string | null }[];
  calendar_event: { id: string; provider: "google" | "ics"; starts_at: string } | null;
}

// GET /planner/tasks
export interface PlannerTask {
  id: string;
  title: string;
  due_date: string;
  is_done: boolean;
  source: "prep_plan" | "syllabus" | "lms_assignment" | "lms_announcement" | "manual";
  link: {
    type: "opportunity" | "syllabus_item" | "lms_assignment" | "lms_announcement" | null;
    id: string | null;
    title: string | null;                // 공고 제목 또는 과목명
    category: Category | null;           // 공고에서 온 할 일만
    html_url?: string;
  };
  auto_completed?: boolean;              // LMS 제출로 자동 완료
}
export interface PlannerMarker { kind: "deadline"; date: string; title: string; opportunity_id: string; category: Category; }
export interface PlannerResponse { items: PlannerTask[]; markers: PlannerMarker[]; }

// GET /lms/connection
export interface LmsConnection {
  status: "active" | "error" | "disconnected";
  token_last4: string;
  last_synced_at: string | null;
  last_error: string | null;
}

// GET /lms/courses
export interface Course {
  id: string;
  canvas_course_id: number;
  name: string;
  short_name: string;
  has_syllabus: boolean;
  portal_syllabus_url: string;
  open_assignments: number;
  new_materials: number;
  next_due: { kind: "assignment" | "syllabus"; title: string; due_at: string } | null;
}

// GET /lms/courses/{id}
export type SubmissionState = "unsubmitted" | "submitted" | "graded" | "pending_review";
export type AnnouncementCategory = "schedule_change" | "material" | "opportunity" | "general";
export interface CourseDetail {
  course: { id: string; short_name: string; has_syllabus: boolean; portal_syllabus_url: string };
  assignments: { id: string; title: string; due_at: string | null; submission_state: SubmissionState; html_url: string }[];
  module_items: { id: string; module_name: string; title: string; html_url: string; is_new: boolean; uploaded_file_id: string | null }[];
  announcements: { id: string; title: string; summary: string | null; category: AnnouncementCategory | null; posted_at: string; opportunity_id: string | null }[];
  syllabus_items: { id: string; item_type: "midterm" | "final" | "presentation" | "assignment" | "etc"; title: string; starts_at: string | null; is_confirmed: boolean }[];
  materials: { file_id: string; original_name: string | null; status: RunStatus }[];
}

// GET /materials/{file_id}: 강의자료 요약·구간 번역 (TODO(api): API 명세 8장 응답과 필드 이름 대조)
export interface MaterialDetail {
  file_id: string;
  original_name: string | null;
  total_pages: number;
  page_start: number;
  page_end: number;
  over_limit: boolean;
  overall_summary: string | null;
  status: RunStatus;
  sections: {
    id: string;
    seq: number;
    title: string;
    page_start: number;
    page_end: number;
    summary: string | null;
    translation_status: RunStatus | null; // null이면 번역 요청 전
    translation_url: string | null;
  }[];
}

// GET /lms/updates
export type LmsUpdate =
  | { type: "module_item"; id: string; course: { id: string; short_name: string }; module_name: string; title: string; html_url: string; first_seen_at: string; uploaded_file_id: string | null }
  | { type: "announcement"; id: string; course: { id: string; short_name: string }; title: string; summary: string | null; posted_at: string; category: AnnouncementCategory | null; attachment_count: number; opportunity_id: string | null; planner_task_id: string | null }
  | { type: "assignment"; id: string; course: { id: string; short_name: string }; title: string; due_at: string; submission_state: SubmissionState };

// GET /notifications
export interface AppNotification {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  scheduled_at: string;
  read_at: string | null;
  link: {
    type: "opportunity" | "planner_task" | "lms_assignment" | "lms_module_item" | "lms_announcement";
    id: string;
    focus?: "profile_input";
  };
}
```
````

확인할 것

- [ ] 화면 모양이 그대로다
- [ ] `src/types/api.ts`가 위 코드와 같다
- [ ] App.tsx가 짧아지고 screens·components로 나뉘었다

---

## 프롬프트 1 · 목데이터와 상태 미리보기

````text
src/types/api.ts 타입을 따르는 목데이터와 데이터 함수를 만들고, 화면이 이걸 쓰게 바꿔줘.

1. src/mocks/에 한국어 목데이터를 만들어줘. 오늘은 2026-10-05(월)로 고정해. 꼭 들어갈 것:
   - me: display_name "진서", consented true, unread_notifications 3, lms active, calendar_connected true, profile_completion 9/15
   - 공고 12개: display_status 4종 모두, 지원 어려움 3개, needs_review가 true인 지원 가능 1개, 마감일 없는 공고 1개, D-day·D-1·D-3 마감 각 1개, is_new 2개, 포스터 공고 2개(uploader_masked "김*지", "박*"), 과목 공지 공고 1개(course_name "데이터베이스"), 카테고리 6종 이상. 주최는 실제처럼(ERICA 학생지원팀, 경기도, ○○도시공사 등)
   - 공고 상세: conditions에 pass·fail·unknown을 섞고 evidence_text를 채워줘. documents에는 lead_days 0과 2, effort_minutes 30, form_url 1개. process.extraction 3단계
   - 준비 중인 공고 1개: prep.prepared true, 서류 3개 중 1개 완료(해당 플래너 할 일도 완료)
   - 플래너 10월 할 일 10개(prep_plan·lms_assignment·syllabus·manual 섞기, 일부 완료, auto_completed 1개)와 markers 2개
   - 과목 4개(선형대수, 해석학, DS창업캡스톤디자인1, 데이터베이스)와 과목마다 상세: 과제 3, 주차 자료 4개 중 is_new 2, 공지 3개(category 3종, summary), 계획서 일정 3, 강의자료 1개(MaterialDetail, 구간 5개)
   - 알림 6개: type 5종 이상, 3개 안 읽음, profile_needed 1개는 link.focus "profile_input"
2. src/api/client.ts에 getMe, getProfile, getSettings, getFeed(params: eligibility, category, sort), getOpportunity(id), getPlanner(from, to), getLmsConnection, getCourses, getCourse(id), getLmsUpdates, getNotifications, getMaterial(fileId)를 만들고 목데이터를 300ms 뒤 Promise로 돌려줘. getFeed는 params대로 거르고 정렬한 뒤 counts까지 계산해줘.
3. 모든 화면이 client.ts 함수로만 데이터를 받게 바꾸고, 화면 안의 예시 배열은 지워줘. 불러오는 동안에는 회색 스켈레톤.
4. 오른쪽 아래에 개발용 "상태 미리보기" 버튼을 두고 시나리오를 바꿀 수 있게 해줘: 기본 / 첫 접속(동의 전) / LMS 미연결 / LMS 오류 / 캘린더 만료 / 빈 피드. client.ts가 현재 시나리오에 맞는 데이터를 돌려주면 돼. 이 코드는 src/dev/에만 둬.
````

확인할 것

- [ ] 홈 숫자가 목데이터 counts와 맞다
- [ ] 상태 미리보기로 시나리오 6개가 바뀐다
- [ ] 화면 파일에 예시 배열이 남지 않았다

---

## 프롬프트 2 · 표기와 라벨

````text
AGENTS.md의 판정 라벨·기준값대로 공통 표기를 정리해줘.

1. src/components/StatusBadge.tsx: display_status를 받아 라벨과 톤을 정해. Badge에 gray 톤(#475467 / #f2f4f7)을 추가해줘.
2. 홈 요약 카드: "지원 가능 {eligible}" 아래 "새 공고 {new_eligible}개", "확인 필요 {undetermined}" 아래 "정보 입력 {missing_info} · 원문 확인 {needs_review}", "마감 임박 {deadline_soon}" 아래 "3일 이내".
3. 카테고리 칩: 전체 · 장학금 · 교내 프로그램 · 청년정책 · 공모전 · 대외활동 · 기타(research, exam, etc).
4. 공고 카드 윗줄 기관명은 organizer로. 포스터 공고는 "{uploader_masked}님 공유", 과목 공지 공고는 "{course_name} 수강생 대상".
5. 카드 아랫줄 "원문 확인 가능"을 출처와 "원문 보기"로 바꿔줘(포스터 공고는 "포스터 보기").
6. 플래너 하단 문구: "준비 중인 공고 마감일과 LMS 과제 마감일을 Google Calendar에 등록해요".
7. 상세 서류 줄: lead_days가 0이면 "{issuer} · 즉시 발급", 아니면 "{issuer} · 발급 {n}일". effort_minutes가 있으면 " · 작성 약 {m}분"을 붙이고, form_url이 있으면 "양식 내려받기" 링크.
8. 카드·상세·알림 어디서든 마감 임박은 D-3 기준으로 표시해줘.
````

확인할 것

- [ ] 라벨 4종과 gray 톤이 보인다
- [ ] 카드 기관명이 공고마다 다르다
- [ ] 서류 줄에 "즉시 발급", "작성 약 30분"이 나온다

---

## 프롬프트 3 · 홈

````text
홈 화면 동작을 고쳐줘. 데이터는 getFeed.

1. 요약 카드 3개를 누르면 목록을 그 상태로 거른다: 지원 가능 / 확인 필요(정보 필요 + 원문 확인 필요) / 마감 임박. 선택된 카드는 테두리 #4f6ef7, 다시 누르면 해제. 카테고리 칩과 함께 적용해줘.
2. 목록은 지원 가능·확인 필요 공고만 보여주고, 맨 아래에 "지원 어려움 {ineligible}개" 묶음을 접어서 둬. 펼치면 지원 어려움 카드가 나오고 카드마다 탈락 사유 한 줄.
3. 정렬 드롭다운: 마감 임박순(기본, 마감일 없는 공고는 맨 뒤에 "상시")과 최신순.
4. is_new인 공고는 제목 앞에 작은 파란 점.
5. 거른 결과가 0개면 "조건에 맞는 공고가 없어요"와 "필터 초기화" 버튼. 빈 피드 시나리오에서는 "포스터를 올리면 공고로 등록하고 자격을 판정해요"와 "포스터 등록" 버튼.
6. 카드를 누르면 { name: "opportunity", id }로 이동.
````

확인할 것

- [ ] 요약 카드를 누르면 목록이 걸러진다
- [ ] 지원 어려움 공고는 맨 아래 묶음에만 있다
- [ ] 마감일 없는 공고가 맨 뒤에 "상시"로 나온다

---

## 프롬프트 4 · 공고 상세 상태별 화면

````text
공고 상세를 display_status별로 다르게 보여줘. 데이터는 getOpportunity(id).

1. 상단 상태 카드: 라벨, 사유(지원 어려움은 reason_text, 나머지는 summary), "마감까지 N일" 또는 "상시 모집", 신청 기간(apply_start_at ~ deadline_at).
2. 주 행동 버튼: 지원 가능 "준비 일정 만들기" / 정보 필요 "정보 입력" / 원문 확인 필요 "원문 보기" / 지원 어려움 "대체 공고 보기"(아직 비활성, 툴팁 "대체 공고 추천은 준비 중이에요").
3. 조건별 판정표: 행마다 condition_text, 내 값(user_value_text, 없으면 "미입력"), 결과 배지(충족 green / 불충족 red / 확인 필요 yellow). 행을 누르면 아래로 "공고 원문: {evidence_text}"가 펼쳐진다. 지원 어려움이면 불충족 행을 맨 위로 올리고 내 값을 빨간색으로.
4. 정보 입력: 버튼을 누르면 모달에 missing_fields 항목만 입력란으로 보여줘(라벨은 해당 조건의 label). 소득·수급 항목 위에는 "자격 판정에만 쓰고, 탈퇴하면 바로 지워요". 저장하면 0.8초 뒤 다시 판정한 결과로 상세를 갱신하는 목업 동작과 토스트 "다시 판정했어요".
5. needs_review가 true인 지원 가능 공고는 라벨 옆에 작은 gray "원문 확인 필요" 배지.
6. 제목 오른쪽에 "원문 보기": original_url은 새 탭, 포스터 공고는 poster_url 이미지를 모달로.
7. 포스터 공고는 상태 카드 아래 "{uploader_masked}님이 공유한 포스터예요"와 "신고" 버튼. 신고 모달은 잘못된 정보 / 중복 / 마감됨 / 부적절 중 하나와 상세 입력 → 토스트 "신고했어요". reported_by_me면 버튼을 "신고함"으로 비활성.
8. Route에 focus: "profile_input"이 있으면 정보 입력 모달을 바로 열어줘.
````

확인할 것

- [ ] 4가지 상태가 각각 다르게 보인다
- [ ] 정보 입력을 저장하면 결과가 바뀐다
- [ ] 포스터 공고에 업로더와 신고 버튼이 보인다

---

## 프롬프트 5 · 준비하기

````text
상세의 "준비 일정 만들기"를 실제 흐름처럼 만들어줘(목업).

1. 누르면 상태 카드 아래에 처리 과정이 단계별로 나타나: "필요 서류 확인" → "마감일에서 거꾸로 일정 짜기". 단계마다 0.6초 간격으로 진행 중 → 완료.
2. 끝나면 결과 카드: 만들어진 할 일 목록(서류마다 1개 + "신청서 제출" 1개, 날짜 표시)과 "마감일을 Google Calendar에도 넣기" 체크박스(기본 체크, 캘린더 만료 시나리오에서는 비활성 + "캘린더를 다시 연결해야 해요"). "완료"를 누르면 토스트 "준비 일정을 만들었어요"와 "플래너에서 보기" 링크.
3. 이미 준비한 공고(prep.prepared): 버튼 자리에 진행 막대 "서류 {tasks_done}/{tasks_total} 완료"와 "플래너에서 보기".
4. 서류 체크박스: 준비 전에는 비활성 + "준비 일정을 만들면 체크할 수 있어요". 준비 후 체크하면 플래너의 같은 할 일(task_id)도 완료로 바뀌게 목데이터 상태를 공유해줘.
5. 지원 어려움 공고는 "대체 공고 보기" 옆에 보조 버튼 "그래도 준비하기". 누르면 확인 모달 "지원 조건을 충족하지 못한 공고예요. 그래도 준비 일정을 만들까요?" 후 1번 흐름.
6. 상세 아래쪽 "AI 처리 과정" 접이식: process.extraction 단계(라벨, 소요 시간), "내 프로필과 비교 · {evaluated_at}", 준비했으면 준비 단계까지.
````

확인할 것

- [ ] 준비 전에는 서류 체크가 안 된다
- [ ] 상세에서 체크하면 플래너에서도 완료로 보인다
- [ ] 이미 준비한 공고는 진행률이 보인다

---

## 프롬프트 6 · 포스터 등록

````text
포스터 등록 화면을 상태별로 만들어줘. 결과 형태는 PosterExtractResult.

1. 업로드 영역: JPG·PNG·WEBP·HEIC 또는 2쪽 이하 PDF, 20MB 이하. 760px 이하 화면에서는 "파일 선택" 옆에 "사진 찍기" 버튼(input capture="environment").
2. 파일을 고르면 분석 중: 왼쪽에 원본 미리보기, 오른쪽에 처리 과정 3단계("포스터에서 글자·날짜 읽기" → "지원 자격 정리" → "내 프로필과 비교")가 차례로 완료.
3. 분석 완료: 오른쪽에 확인 폼. 공고명, 주최, 카테고리(선택), 신청 시작·마감, 지원 자격(condition_text 목록, 행마다 삭제), 필요 서류 목록. low_confidence_fields에 있는 필드는 노란 테두리와 "확인해 주세요". "정보 수정"을 누르면 편집할 수 있게.
4. 등록 버튼 위에 "등록하면 다른 학생 피드에도 공개되고, 이름은 김*지처럼 가려져요."
5. duplicate_candidate가 있으면 폼 대신 "이미 등록된 공고예요" 카드: 기존 공고 제목과 "기존 공고 보기"(상세로 이동).
6. 실패: "글자를 읽지 못했어요. 포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요"와 "다시 올리기".
7. 하루 업로드 한도 초과: "오늘은 더 올릴 수 없어요. 내일 0시부터 다시 올릴 수 있어요".
8. "공고 등록하고 자격 확인"을 누르면 토스트 "공고를 등록했어요" 후 새 공고 상세로 이동.
9. 실패·중복·한도 상태는 상태 미리보기에서도 고를 수 있게 해줘.
````

확인할 것

- [ ] 분석 중 → 완료 → 등록까지 이어진다
- [ ] 실패·중복·한도 화면을 상태 미리보기로 볼 수 있다
- [ ] 좁은 화면에서 "사진 찍기"가 보인다

---

## 프롬프트 7 · 학업과 LMS 연결

````text
학업 화면을 보완하고 LMS 연결 흐름을 만들어줘.

1. 과목 카드: "과제 {open_assignments}", "새 자료 {new_materials}", 다음 일정(next_due, 없으면 "예정된 일정 없음"). 카드 전체를 누르면 과목 상세로.
2. "새로 들어온 학업 정보"는 getLmsUpdates로: 주차 자료, 공지(한 줄 요약), 과제(새 과제·마감 임박). 누르면 해당 과목 상세의 맞는 탭으로.
3. 연결 상태 띠: active면 지금처럼 "LearningX 연결됨 · 마지막 동기화 …". error면 빨간 띠 "LearningX 연결이 끊겼어요. 토큰이 만료됐거나 삭제됐어요"와 "다시 연결". 미연결이면 학업 화면 전체를 연결 안내로.
4. LMS 연결 화면(단계형 모달): ① 발급 안내 "LearningX > 계정 > 설정 > 승인된 통합 > + 새 액세스 토큰"과 캡처 자리 3칸(회색 박스) ② 토큰 붙여넣기 입력(가려서 표시) ③ "연결하기" → 확인 중 → 성공 "8개 과목을 불러왔어요" 또는 실패 "토큰을 확인할 수 없어요. 복사할 때 앞뒤 공백이 들어갔는지 확인해 주세요".
5. 토큰은 어디에도 원문으로 보여주지 말고 끝 4자리만.
````

확인할 것

- [ ] LMS 오류·미연결 시나리오가 각각 다르게 보인다
- [ ] 토큰이 끝 4자리 말고는 보이지 않는다
- [ ] 학업 피드를 누르면 과목 상세의 맞는 탭으로 간다

---

## 프롬프트 8 · 과목 상세

````text
과목 상세 화면을 만들어줘. 데이터는 getCourse(id)이고, Route의 tab으로 첫 탭을 고른다.

1. 상단: 과목명, "LMS에서 열기", 마지막 동기화 시각. 탭 4개: 과제 / 자료 / 공지 / 계획서.
2. 과제: 마감순, 제출 상태 배지(미제출 red, 제출 green, 채점 완료 gray), "LMS에서 제출" 링크. 제출한 과제는 아래로.
3. 자료: 주차별 묶음, 새 항목은 "새 자료" 배지. 항목마다 "LMS에서 열기"(안내 한 줄 "LMS에서 직접 열어야 학습 완료가 인정돼요")와 "받은 PDF 올려서 요약하기". 이미 올린 자료는 "요약 보기".
4. 요약 보기(오른쪽 패널, getMaterial): 전체 요약, 구간 목록(제목, 쪽 범위, 구간 요약). 구간마다 체크박스 → "선택한 구간 번역하기" → 번역 중 → 완료되면 "번역본 열기". over_limit이면 맨 위에 "분량이 많아요. 1–40쪽처럼 범위를 골라 주세요"와 쪽 범위 입력.
5. 공지: 분류 배지(일정 변경 / 자료 배포 / 기회 / 일반)와 한 줄 요약. 기회 공지는 "공고로 보기"(opportunity_id 상세로).
6. 계획서: has_syllabus가 false면 "포털에서 강의계획서 열기"(portal_syllabus_url, 새 탭)와 "PDF로 저장해 올려 주세요" 안내, 업로드 영역. 올리면 추출된 일정(중간·기말·발표·과제)을 날짜 수정 가능하게 보여주고 "확인하고 플래너에 넣기". 있으면 확정된 일정 목록.
````

확인할 것

- [ ] 탭 4개가 모두 채워져 있다
- [ ] 구간을 골라 번역하는 흐름이 있다
- [ ] 계획서가 없을 때 포털 바로가기와 업로드가 보인다

---

## 프롬프트 9 · 플래너

````text
플래너를 보완해줘. 데이터는 getPlanner(from, to).

1. 캘린더 칸에 할 일 칩과 markers를 함께 그려줘. 마감 칩은 테두리만 있는 스타일에 "마감"을 붙이고 체크할 수 없게.
2. 칩 색: 공고에서 온 할 일은 파란 계열에 카테고리 이름, LMS·강의계획서 할 일은 빨간 계열에 과목명(지금 시안 유지).
3. 날짜를 누르면 오른쪽 패널이 그 날짜의 할 일로 바뀐다. 제목은 "10월 7일 수요일", 아래 "할 일 N개".
4. "+ 일정 추가": 제목·날짜 입력 → 목록에 추가(source manual). 직접 추가한 항목만 ⋯ 메뉴로 수정·삭제.
5. LMS 과제는 체크할 수 있고, auto_completed면 제목 아래 "제출 확인됨".
6. 하단 Google Calendar 띠: 연결됨과 연결 만료("다시 로그인해서 연결해 주세요" + 버튼) 두 상태.
````

확인할 것

- [ ] 마감 칩은 체크되지 않는다
- [ ] 날짜를 누르면 오른쪽 목록이 바뀐다
- [ ] 직접 추가한 항목만 수정·삭제된다

---

## 프롬프트 10 · 알림 패널

````text
알림 패널을 실제처럼 동작하게 해줘. 데이터는 getNotifications, 헤더 숫자는 me.unread_notifications.

1. 헤더의 "알림 3" 배지와 파란 원 버튼을 종 모양 버튼 하나로 합치고, 안 읽은 수는 버튼 위 작은 숫자 배지로.
2. 패널 항목: 종류별 점 색(마감 임박 red, 새 과제·새 자료 blue, 프로필 정보 필요 yellow, 일정 변경 gray), 제목, 본문, 상대 시각("1시간 전"). 안 읽은 항목은 배경 #eef2ff.
3. 항목을 누르면 읽음 처리하고 link로 이동해: opportunity → 공고 상세(focus가 있으면 함께 전달), lms_* → 과목 상세의 맞는 탭, planner_task → 플래너.
4. 패널 위쪽에 "모두 읽음". 알림이 없으면 "새 알림이 없어요".
````

확인할 것

- [ ] 알림을 누르면 숫자가 줄고 해당 화면으로 간다
- [ ] 프로필 정보 필요 알림이 정보 입력 모달을 연다

---

## 프롬프트 11 · 설정

````text
사이드바 "설정"을 누르면 열리는 설정 화면을 만들어줘.

1. 내 프로필: 학적·성적·나이·지역·소득 항목 요약과 채운 비율(profile_completion), "수정"(온보딩 입력 폼 재사용). 저장하면 토스트 "프로필을 바꿨어요. 공고를 다시 판정했어요".
2. 연결된 서비스: Google Calendar(연결됨 / 만료 → "다시 연결"), LearningX(토큰 끝 4자리, 마지막 동기화, "연결 해제"). 연결 해제 확인 모달: "연결을 해제하면 토큰을 바로 지워요. LearningX 설정에서도 토큰을 삭제해 주세요."
3. 알림(P1 표시): 푸시 알림 켜기, 종류별 끄기 토글, "LMS 과제 마감을 Google Calendar에 자동으로 넣기".
4. 재학생 인증(P1 표시): "HY-in으로 재학생 인증" 비활성 버튼.
5. 계정: "탈퇴" → 확인 모달 "모든 개인 정보와 토큰을 지워요. 공유한 포스터 공고는 이름 없이 남아요." 입력창에 "탈퇴"를 입력해야 버튼이 켜진다.
````

확인할 것

- [ ] 연결 해제와 탈퇴에 확인 단계가 있다
- [ ] P1 항목에 P1 표시가 있다

---

## 프롬프트 12 · 로그인·온보딩

````text
첫 접속 흐름을 만들어줘. me.consented가 false면 이 흐름부터 보여줘(상태 미리보기의 "첫 접속").

1. 로그인: 서비스 이름, 한 줄 소개 "지원할 수 있는 장학금·정책·공모전을 찾아 준비 일정까지 만들어요", "Google로 시작하기" 버튼, 그 아래 "마감일을 Google Calendar에 넣기 위해 캘린더 권한을 함께 요청해요".
2. 동의: 이용약관(필수), 개인정보 수집·이용(필수) 체크와 각각 "보기". 둘 다 체크해야 "다음".
3. 프로필 4단계(진행 막대, 단계마다 "건너뛰기"):
   ① 학적: 학과, 학년, 재학 상태, 이수 학기 수
   ② 성적: 누적 취득학점, 직전학기 취득학점, 누적 평점, 직전학기 장학용 평점(F 포함), 평점 만점(기본 4.5)
   ③ 나이·지역: 생년월일, 병역 복무 개월 수(해당자만), 거주지역(시·도, 시·군·구)
   ④ 소득: 학자금 지원구간, 기준 중위소득 %, 기초생활수급·차상위 여부. 단계 위에 "자격 판정에만 쓰고, 탈퇴하면 바로 지워요".
4. 마지막: "LearningX도 연결할까요? 과제 마감과 새 자료를 알려드려요" → "연결하기"(LMS 연결 화면) / "나중에".
5. 모두 건너뛰어도 홈으로 들어간다. 이때 정보 필요 공고가 많아지는 게 정상이야.
````

확인할 것

- [ ] "첫 접속" 시나리오에서 로그인부터 시작한다
- [ ] 동의 없이는 다음 단계로 못 간다
- [ ] 모두 건너뛰어도 홈에 들어간다

---

## 프롬프트 13 · 다듬기 (P1)

````text
마무리로 다듬어줘.

1. lucide-react를 설치해서 아이콘을 바꿔줘: 홈 Home, 플래너 CalendarDays, 학업 BookOpen, 문서함 FolderOpen, 포스터 등록 ImagePlus, 설정 Settings, 알림 Bell.
2. 빈 상태를 채워줘: 오늘 할 일 없음("오늘은 할 일이 없어요" + "일정 추가"), 과목 공지 없음, 알림 없음, LMS 미연결 학업("LearningX를 연결하면 과제 마감과 새 자료를 알려드려요" + "연결하기").
3. 760px 이하에서는 플래너 월간 칸 대신 주간 목록으로 보여줘.
````

확인할 것

- [ ] 사이드바·헤더 아이콘이 바뀌었다
- [ ] 좁은 화면에서 플래너가 주간 목록으로 바뀐다

---

## 프롬프트 14 · 남은 화면 (P1)

````text
P1 화면을 추가해줘.

1. 대체 공고: 지원 어려움 상세의 "대체 공고 보기"를 켜고, 누르면 같은 카테고리의 지원 가능 공고 최대 3개를 카드로 보여줘.
2. 문서함: 사이드바 메뉴를 다시 보이게 하고, 올린 강의자료·강의계획서 목록(과목, 올린 날, 요약 상태)과 요약 보기를 연결해줘.
3. 알림 전체 보기: 패널의 "모든 알림 확인하기" → 전체/안 읽음 탭이 있는 알림 화면.
4. 캘린더 파일: 공고 상세와 플래너에 "캘린더 파일(.ics) 받기" 버튼(Google Calendar를 쓰지 않는 사람용).
````

확인할 것

- [ ] 대체 공고 카드에서 상세로 이동한다
- [ ] 문서함 메뉴가 보이고 요약 보기와 이어진다
