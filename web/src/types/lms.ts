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
  // 캘린더에 실제로 들어간 일정인지. 확인 화면(추출 결과)에서는 늘 false다
  calendar_registered: boolean;
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
// 공지 첨부의 내 저장 상태(F-54): saved 문서함에 받음 · too_large 20MB가 넘어 받지 않음 · pending 아직(다음 동기화가 받는다)
export type AttachmentStatus = "saved" | "too_large" | "pending";
export interface AnnouncementAttachment {
  name: string;
  size_bytes: number | null;
  status: AttachmentStatus;
  file_id: string | null; // 저장했으면 내 파일 번호
}
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
    attachments: AnnouncementAttachment[]; // 첨부가 없으면 빈 목록(F-54)
  }[];
  syllabus_items: SyllabusItemView[];
  materials: {
    file_id: string;
    original_name: string | null;
    status: RunStatus;
  }[];
}

// GET /materials/{file_id}: 강의자료 요약(F-15 축소판, API 명세 8장). 요약은 Markdown이다.
// 구간 요약·번역은 확장 범위라 없다. 요약을 아직 안 했으면 status는 pending이다
export interface MaterialDetail {
  file_id: string;
  file_name: string | null;
  course: { lms_course_id: string; name: string } | null;
  source_language: string | null; // 축소판은 늘 null
  total_pages: number | null;
  processed_range: { start: number; end: number } | null;
  status: RunStatus;
  overall_summary: string | null;
  over_limit: boolean; // 글자가 상한을 넘어 요약하지 않았다
  run_id: string | null; // 마지막 요약 실행(진행·실패 이유는 GET /runs/{id})
}

// POST /materials가 끝났을 때 GET /runs/{id}의 result
export interface MaterialSummaryResult {
  kind: "material_summary";
  file_id: string;
  overall_summary: string;
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

// 문서함 (F-44, API 명세 6장). 내 강의자료(공지 첨부 포함)·강의계획서. 포스터는 공고 쪽에 있어 넣지 않는다
export type MyFileKind = "lecture_material" | "syllabus";
export type MyFileOrigin = "upload" | "lms_attachment"; // 직접 올림 · 공지 첨부를 동기화가 받음
// 파일의 과목. 수강을 뺀(지난 학기) 과목은 is_active가 false이고 과목 화면이 열리지 않는다
export interface MyFileCourse {
  id: string;
  short_name: string;
  is_active: boolean;
}
// GET /files?limit=&cursor= — 받은 순(최신 먼저)
export interface MyFile {
  file_id: string;
  file_name: string; // 원래 이름. 없으면 "파일.<확장자>"
  kind: MyFileKind;
  origin: MyFileOrigin;
  course: MyFileCourse | null; // 과목을 모르면 null
  size_bytes: number | null;
  created_at: string;
}
export interface MyFileList {
  items: MyFile[];
  next_cursor: string | null;
}
// GET /files/{id}/url — 5분 동안 열리는 받기 주소. 열면 원래 이름으로 내려받는다(주소를 들고 있지 않는다)
export interface FileDownloadUrl {
  url: string;
  expires_at: string;
}
