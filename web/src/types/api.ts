// API 명세와 1:1로 맞춘 타입. 필드 이름을 바꾸지 않는다. LMS·강의자료 타입은 lms.ts에 두고 여기서 다시 내보낸다.
// 내 정보·프로필·동의·학과·사용 기록은 v0.4에 맞췄다. 공고 피드·상세는 아직 v0.3 모양이다
// (TODO(api): 공고 화면을 실제 API에 붙일 때 명세 부록 "프론트 반영 목록"대로 맞춘다)
// 일시는 ISO 8601 문자열(+09:00), 날짜만은 "YYYY-MM-DD".

export * from "@/types/lms";

export type Category = "scholarship" | "school_program" | "youth_policy" | "contest" | "activity" | "research" | "exam" | "etc";
export type SourceType = "school_notice" | "youth_policy" | "contest" | "poster" | "lms_announcement";
export type EligibilityStatus = "eligible" | "undetermined" | "ineligible";
export type DisplayStatus = "eligible" | "missing_info" | "needs_review" | "ineligible";
export type RunStatus = "pending" | "running" | "succeeded" | "failed";
export type NotificationType =
  | "new_eligible" | "new_assignment" | "new_material" | "schedule_change"
  | "task_due" | "deadline_soon" | "profile_needed";
export type ReportReason = "wrong_info" | "duplicate" | "expired" | "inappropriate";

// GET /me
export interface Me {
  user_id: string;
  display_name: string;
  hyin_verified: boolean;
  calendar_connected: boolean;
  lms: { status: "active" | "error" | "disconnected"; last_synced_at: string | null } | null;
  profile_completion: { filled: number; total: number };
  consented: boolean;
  income_info_consented: boolean;
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
  is_international: boolean | null;
}

// PATCH /me/profile: 저장한 프로필과 다시 판정한 결과 수 (counts와 같은 기준)
export interface ProfileUpdateResponse {
  profile: Profile;
  rejudged: { changed: number; eligible: number; undetermined: number; ineligible: number };
}

// POST /me/consents
export interface ConsentResult {
  terms_agreed_at: string;
  privacy_agreed_at: string;
  income_info_agreed_at: string | null;
  consent_version: string;
}

// PATCH /me/consents
export interface IncomeConsentResult {
  income_info_agreed_at: string | null;
}

// GET /meta/departments의 items
export interface Department {
  name: string;
  college: string;
  field_group: string;
}

// POST /events: 화면에서만 알 수 있는 사용 기록 (나머지 이벤트는 서버가 기록한다)
export type ClientEvent = "app_open" | "profile_prompt_shown" | "lms_guide_opened";

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
    summary: string;                     // 상태 사유 한 줄 (API v0.3 보완)
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
    course_id?: string;                  // lms_* 링크의 과목 ID (API v0.3 보완)
    focus?: "profile_input";
  };
}
