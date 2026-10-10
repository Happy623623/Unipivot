import { getDevScenario } from "@/dev/scenarios";
import {
  courseDetails,
  courses,
  lmsUpdates,
  materials,
  mockNow,
  mockToday,
  opportunities,
  opportunityDetails,
  duplicatePosterExtractResult,
  posterExtractResult,
} from "@/mocks";
import {
  connectStoredLms,
  getStoredLmsConnection,
  getStoredMe,
  getStoredProfile,
  getStoredSettings,
  hasStoredConsent,
} from "@/mocks/accountStore";
import {
  getStoredOpportunity,
  getStoredPlanner,
  addStoredManualTask,
  deleteStoredManualTask,
  prepareStoredOpportunity,
  registerStoredPoster,
  setStoredPlannerTaskDone,
  setStoredDocumentDone,
  updateStoredManualTask,
} from "@/mocks/store";
import type {
  AppNotification,
  Category,
  Course,
  CourseDetail,
  DisplayStatus,
  FeedCounts,
  FeedResponse,
  LmsConnection,
  LmsUpdate,
  MaterialDetail,
  Me,
  OpportunityDetail,
  PlannerResponse,
  PlannerTask,
  PosterExtractResult,
  PrepareResult,
  Profile,
  ReportReason,
  Settings,
} from "@/types/api";

export interface FeedParams {
  eligibility?: DisplayStatus | "all";
  category?: Category | "all";
  sort?: "deadline" | "recent";
}

export const MOCK_TODAY = mockToday;
export const MOCK_NOW = mockNow;
const WAIT_MS = 300;

export type PosterPreviewState =
  | { status: "idle"; result: null }
  | { status: "failure"; result: null }
  | { status: "limit"; result: null }
  | { status: "duplicate"; result: PosterExtractResult };

export class MockApiError extends Error {
  constructor(
    public code: "poster_read_failed" | "upload_limit" | "lms_invalid",
    message: string,
  ) {
    super(message);
  }
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function respond<T>(value: T): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(clone(value)), WAIT_MS);
  });
}

function rejectAfter(error: Error): Promise<never> {
  return new Promise((_, reject) => {
    setTimeout(() => reject(error), WAIT_MS);
  });
}

function getCounts(items: FeedResponse["items"]): FeedCounts {
  return {
    eligible: items.filter((item) => item.eligibility.status === "eligible").length,
    new_eligible: items.filter((item) => item.eligibility.status === "eligible" && item.is_new).length,
    undetermined: items.filter((item) => item.eligibility.status === "undetermined").length,
    missing_info: items.filter((item) => item.eligibility.display_status === "missing_info").length,
    needs_review: items.filter((item) => item.eligibility.display_status === "needs_review").length,
    ineligible: items.filter((item) => item.eligibility.status === "ineligible").length,
    deadline_soon: items.filter((item) => item.eligibility.status !== "ineligible" && item.d_day !== null && item.d_day >= 0 && item.d_day <= 3).length,
  };
}

export function getMe(): Promise<Me> {
  const scenario = getDevScenario();
  const result = clone(getStoredMe());

  if (scenario === "first_visit" && !hasStoredConsent()) {
    result.consented = false;
    result.income_info_consented = false;
  }
  if (scenario === "lms_disconnected") {
    result.lms = { status: "disconnected", last_synced_at: null };
  }
  if (scenario === "lms_error" && result.lms) result.lms.status = "error";
  if (scenario === "calendar_expired") result.calendar_connected = false;

  return respond(result);
}

export function getProfile(): Promise<Profile> {
  return respond(getStoredProfile());
}

export function getSettings(): Promise<Settings> {
  return respond(getStoredSettings());
}

export function getFeed(params: FeedParams = {}): Promise<FeedResponse> {
  if (getDevScenario() === "empty_feed") {
    return respond({ items: [], next_cursor: null, counts: getCounts([]) });
  }

  let items = [...opportunities];
  if (params.eligibility && params.eligibility !== "all") {
    items = items.filter((item) => item.eligibility.display_status === params.eligibility);
  }
  if (params.category && params.category !== "all") {
    items =
      params.category === "etc"
        ? items.filter((item) => ["research", "exam", "etc"].includes(item.category))
        : items.filter((item) => item.category === params.category);
  }

  items.sort((a, b) => {
    if (params.sort !== "recent") {
      return (a.d_day ?? Number.MAX_SAFE_INTEGER) - (b.d_day ?? Number.MAX_SAFE_INTEGER);
    }
    // 실제 API는 sort=recent를 받아 서버가 등록순으로 정렬한다. 목업은 새 공고를 앞으로만 보낸다.
    return Number(b.is_new) - Number(a.is_new);
  });

  return respond({ items, next_cursor: null, counts: getCounts(items) });
}

export function getOpportunity(id: string): Promise<OpportunityDetail> {
  const detail = getStoredOpportunity(id) ?? opportunityDetails[id];
  if (!detail) return Promise.reject(new Error("공고를 찾을 수 없어요."));
  return respond(detail);
}

export function getPlanner(from: string, to: string): Promise<PlannerResponse> {
  const storedPlanner = getStoredPlanner();
  return respond({
    items: storedPlanner.items.filter((item) => item.due_date >= from && item.due_date <= to),
    markers: storedPlanner.markers.filter((marker) => marker.date >= from && marker.date <= to),
  });
}

export function setPlannerTaskDone(id: string, isDone: boolean): Promise<PlannerTask> {
  return respond(setStoredPlannerTaskDone(id, isDone));
}

export function addManualPlannerTask(title: string, dueDate: string): Promise<PlannerTask> {
  return respond(addStoredManualTask(title, dueDate));
}

export function updateManualPlannerTask(id: string, title: string, dueDate: string): Promise<PlannerTask> {
  return respond(updateStoredManualTask(id, title, dueDate));
}

export function deleteManualPlannerTask(id: string): Promise<void> {
  deleteStoredManualTask(id);
  return respond(undefined);
}

// TODO(api): 실제 준비하기 API가 확정되면 전용 엔드포인트 호출로 교체한다.
export function prepareOpportunity(
  id: string,
  includeCalendar: boolean,
  targetDate?: string,
): Promise<PrepareResult> {
  return respond(prepareStoredOpportunity(id, includeCalendar, targetDate));
}

// TODO(api): 실제 서류 완료 API가 확정되면 planner task 수정 엔드포인트로 교체한다.
export function setDocumentDone(
  opportunityId: string,
  documentId: string,
  isDone: boolean,
): Promise<OpportunityDetail> {
  return respond(setStoredDocumentDone(opportunityId, documentId, isDone));
}

// TODO(api): POST /opportunities/{id}/reports { reason, detail } — 서로 다른 3명째 신고에서 hidden: true
export function reportOpportunity(
  _id: string,
  _reason: ReportReason,
  _detail: string,
): Promise<{ reported: boolean; hidden: boolean }> {
  return respond({ reported: true, hidden: false });
}

export function getPosterPreviewState(): Promise<PosterPreviewState> {
  const scenario = getDevScenario();
  if (scenario === "poster_failure") return respond({ status: "failure", result: null });
  if (scenario === "upload_limit") return respond({ status: "limit", result: null });
  if (scenario === "poster_duplicate") {
    return respond({ status: "duplicate", result: duplicatePosterExtractResult });
  }
  return respond({ status: "idle", result: null });
}

// TODO(api): 포스터 추출 run 생성 API와 연결되면 File 대신 업로드된 file_id를 전달한다.
export function extractPoster(_file: File): Promise<PosterExtractResult> {
  const scenario = getDevScenario();
  if (scenario === "poster_failure") {
    return rejectAfter(
      new MockApiError("poster_read_failed", "포스터에서 글자를 읽지 못했어요."),
    );
  }
  if (scenario === "upload_limit") {
    return rejectAfter(
      new MockApiError("upload_limit", "오늘 업로드 한도를 초과했어요."),
    );
  }
  return respond(
    scenario === "poster_duplicate"
      ? duplicatePosterExtractResult
      : posterExtractResult,
  );
}

// TODO(api): 실제 공고 등록 API가 확정되면 draft 등록 요청으로 교체한다.
export function registerPosterOpportunity(
  draft: PosterExtractResult["draft"],
): Promise<OpportunityDetail> {
  return respond(registerStoredPoster(draft));
}

export function getLmsConnection(): Promise<LmsConnection> {
  const scenario = getDevScenario();
  const result = clone(getStoredLmsConnection());
  if (scenario === "lms_disconnected") {
    result.status = "disconnected";
    result.last_synced_at = null;
  }
  if (scenario === "lms_error") {
    result.status = "error";
    result.last_error = "LearningX 인증 정보가 만료됐어요. 다시 연결해 주세요.";
  }
  return respond(result);
}

// TODO(api): LearningX 연결 API가 확정되면 토큰을 서버로만 전달하고 클라이언트에는 저장하지 않는다.
export function connectLms(token: string): Promise<LmsConnection> {
  const normalized = token.trim();
  if (token !== normalized || normalized.length < 8) {
    return rejectAfter(
      new MockApiError("lms_invalid", "LearningX 토큰을 확인할 수 없어요."),
    );
  }
  return respond(connectStoredLms(normalized.slice(-4)));
}

export function getCourses(): Promise<Course[]> {
  return respond(courses);
}

export function getCourse(id: string): Promise<CourseDetail> {
  const course = courseDetails[id];
  if (!course) return Promise.reject(new Error("과목을 찾을 수 없어요."));
  return respond(course);
}

export function getLmsUpdates(): Promise<LmsUpdate[]> {
  return respond(lmsUpdates);
}

export function getMaterial(fileId: string): Promise<MaterialDetail> {
  const material = materials[fileId];
  if (!material) return Promise.reject(new Error("강의자료를 찾을 수 없어요."));
  return respond(material);
}

export {
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/api/notificationClient";
export {
  deleteAccount,
  disconnectLms,
  getDepartments,
  reconnectCalendar,
  saveConsents,
  saveProfile,
  saveSettings,
  updateIncomeConsent,
} from "@/api/settingsClient";
