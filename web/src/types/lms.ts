// LMS·강의자료 타입 (API 명세 8·9장). 화면은 @/types/api에서 가져간다
import type { RunStatus } from "@/types/api";

// 계획서에서 뽑는 일정 종류 (ERD syllabus_item_type). 일반 강의 주차는 넣지 않는다
export type SyllabusItemType = "midterm" | "final" | "presentation" | "assignment" | "etc";

// 계획서 일정 하나 (POST /syllabi/extract 결과·과목 상세 공통, API 명세 8장)
export interface SyllabusItemView {
  id: string;
  item_type: SyllabusItemType;
  title: string;
  starts_at: string | null; // KST 오프셋. 날짜만 적힌 일정은 그날 09:00이다
  is_confirmed: boolean;
}

// GET /runs/{id}의 계획서 추출 결과 (API 명세 8장)
export interface SyllabusExtractResult {
  kind: "syllabus_extract";
  syllabus_id: string;
  course_name: string | null;
  items: SyllabusItemView[];
}

// POST /syllabi/{id}/confirm — 확인 화면이 보내는 일정 하나
export interface SyllabusConfirmItem {
  id: string;
  title: string;
  starts_at?: string | null; // 비우면 저장해 둔 값을 그대로 둔다. 오프셋을 함께 보낸다
  selected: boolean;
}

// POST /syllabi/{id}/confirm 결과
export interface SyllabusConfirmResult {
  confirmed: number;
  planner_tasks_created: number;
  calendar_events_created: number;
  calendar_events_moved: number;
}

// GET /lms/connection
export interface LmsConnection {
  status: "active" | "error" | "disconnected";
  token_last4: string | null;
  last_synced_at: string | null;
  last_error: string | null;
}

// POST /lms/connection — 토큰을 확인하고 수강 과목을 받아 둔 결과(첫 동기화가 바로 시작된다)
export interface LmsConnectResult {
  status: "active";
  token_last4: string;
  courses: number;
  first_sync_run_id: string | null;
}

// GET /lms/courses
export interface Course {
  id: string;
  canvas_course_id: number;
  name: string;
  short_name: string;
  has_syllabus: boolean;
  portal_syllabus_url: string | null; // 과목명 꼴이 달라 번호를 못 뽑으면 null
  open_assignments: number;
  new_materials: number;
  next_due: {
    kind: "assignment" | "syllabus_item";
    title: string;
    due_at: string;
  } | null;
}

// POST /lms/sync (F-51) — 202면 run_id, 5분 안에 이미 받았으면 200 + skipped
export interface SyncStarted {
  run_id: string;
  status: "running";
}
export interface SyncSkipped {
  skipped: true;
  last_synced_at: string | null;
}
export type SyncResponse = SyncStarted | SyncSkipped;

// POST /internal/jobs/lms-sync (30분 배치, 서비스 키로만 부른다 — 프론트에서 쓰지 않는다)
export interface LmsSyncJobResult {
  users: number;
  synced: number;
  failed: number;
  skipped: number;
  new_assignments: number;
  due_changed: number;
  submitted: number;
}

// GET /runs/{id}의 result (kind: "lms_sync"). 공지는 F-53이라 아직 0이다
export interface LmsSyncResult {
  kind: "lms_sync";
  courses: number;
  assignments: { new: number; due_changed: number; submitted: number };
  new_module_items: number;
  new_announcements: number;
  calendar_events: number; // 캘린더에 새로 넣은 과제 마감 수(설정을 켠 사람만)
  calendar_moved: number; // 마감이 바뀌어 시각을 고친 일정 수
}

// GET /lms/assignments?state=open|submitted|all&lms_course_id= (주지 않으면 open)
export type AssignmentState = "open" | "submitted" | "all";
export interface Assignment {
  id: string;
  course: { id: string; short_name: string };
  title: string;
  due_at: string | null; // 마감이 없는 과제도 있다(due_at·lock_at 둘 다 없음)
  submission_state: SubmissionState;
  html_url: string | null;
  planner_task_id: string | null;
  calendar_registered: boolean;
}

// GET /lms/courses/{id}
export type SubmissionState =
  "unsubmitted" | "submitted" | "graded" | "pending_review";
export type AnnouncementCategory =
  "schedule_change" | "material" | "opportunity" | "general";
export interface CourseDetail {
  course: {
    id: string;
    short_name: string;
    html_url: string;
    has_syllabus: boolean;
    syllabus_id: string | null; // 확인 전 일정을 다시 열 때 쓴다(F-14)
    portal_syllabus_url: string | null;
  }; // html_url: 과목 홈 (API v0.3 보완)
  // LMS가 비워 보내는 칸은 null이 올 수 있다(마감 없는 과제, 주차 이름·링크 없는 항목)
  assignments: {
    id: string;
    title: string;
    due_at: string | null;
    submission_state: SubmissionState;
    html_url: string | null;
  }[];
  module_items: {
    id: string;
    module_name: string | null;
    title: string;
    item_type: string | null;
    html_url: string | null;
    is_new: boolean;
    uploaded_file_id: string | null;
  }[];
  announcements: {
    id: string;
    title: string;
    summary: string | null;
    category: AnnouncementCategory | null;
    posted_at: string | null;
    opportunity_id: string | null;
  }[];
  syllabus_items: SyllabusItemView[];
  materials: {
    file_id: string;
    original_name: string | null;
    status: RunStatus;
  }[];
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

// GET /lms/updates?since=&type=module_item,assignment&lms_course_id=&cursor=
// since를 주지 않으면 최근 14일. announcement는 F-53이 채운다(그때까지 비어 있다)
export type LmsUpdateType = "module_item" | "assignment" | "announcement";
export type LmsUpdate =
  | {
      type: "module_item";
      id: string;
      course: { id: string; short_name: string };
      module_name: string | null;
      title: string;
      item_type: string | null;
      html_url: string | null;
      first_seen_at: string;
      uploaded_file_id: string | null;
    }
  | {
      type: "announcement";
      id: string;
      course: { id: string; short_name: string };
      title: string;
      summary: string | null;
      posted_at: string;
      category: AnnouncementCategory | null;
      attachment_count: number;
      opportunity_id: string | null;
      planner_task_id: string | null;
    }
  | {
      type: "assignment";
      id: string;
      course: { id: string; short_name: string };
      title: string;
      due_at: string | null;
      submission_state: SubmissionState;
      html_url: string | null;
      first_seen_at: string;
    };
export interface LmsUpdateList {
  items: LmsUpdate[];
  next_cursor: string | null;
}
