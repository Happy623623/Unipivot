import { MockApiError, rejectAfter, respond } from "@/api/mockClient";
import { getDevScenario } from "@/dev/scenarios";
import {
  mockNow,
  mockToday,
  opportunities,
  opportunityDetails,
  duplicatePosterExtractResult,
  posterExtractResult,
} from "@/mocks";
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
  Category,
  DisplayStatus,
  FeedCounts,
  FeedResponse,
  OpportunityDetail,
  PlannerResponse,
  PlannerTask,
  PosterExtractResult,
  PrepareResult,
  ReportReason,
} from "@/types/api";

// 화면이 쓰는 데이터 함수는 모두 이 파일에서 가져간다.
// 계정·LMS 함수는 accountClient.ts·lmsClient.ts에 두고 여기서 다시 내보낸다. 아래 공고·플래너·포스터 함수는 아직 목이다
export * from "@/api/accountClient";
export * from "@/api/lmsClient";
export { ApiError, consentRequired, errorMessage, fieldErrors } from "@/api/http";
export { MockApiError };

export interface FeedParams {
  eligibility?: DisplayStatus | "all";
  category?: Category | "all";
  sort?: "deadline" | "recent";
}

export const MOCK_TODAY = mockToday;
export const MOCK_NOW = mockNow;

export type PosterPreviewState =
  | { status: "idle"; result: null }
  | { status: "failure"; result: null }
  | { status: "limit"; result: null }
  | { status: "duplicate"; result: PosterExtractResult };

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
