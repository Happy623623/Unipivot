import { ApiError, apiFetch, notReady, USE_MOCKS } from "@/api/http";
import * as mock from "@/api/mockClient";
import { MockApiError, rejectAfter, respond } from "@/api/mockClient";
import { getDevScenario } from "@/dev/scenarios";
import { getKstDateKey } from "@/lib/format";
import { duplicatePosterExtractResult, mockNow, mockToday, posterExtractResult } from "@/mocks";
import { registerStoredPoster } from "@/mocks/posterStore";
import {
  getStoredPlanner,
  addStoredManualTask,
  deleteStoredManualTask,
  prepareStoredOpportunity,
  setStoredPlannerTaskDone,
  setStoredDocumentDone,
  updateStoredManualTask,
} from "@/mocks/store";
import type {
  Category,
  FeedResponse,
  OpportunityDetail,
  OpportunityItem,
  PlannerResponse,
  PlannerTask,
  PosterExtractResult,
  PrepareResult,
  ReportReason,
} from "@/types/api";

// 화면이 쓰는 데이터 함수는 모두 이 파일에서 가져간다.
// 계정·LMS 함수는 accountClient.ts·lmsClient.ts에 두고 여기서 다시 내보낸다.
// 공고 피드·상세는 실제 API를 부르고, 아래 준비하기·플래너·포스터 함수는 아직 목이다
export * from "@/api/accountClient";
export * from "@/api/lmsClient";
export { ApiError, consentRequired, errorMessage, fieldErrors } from "@/api/http";
export { MockApiError };

export interface FeedParams {
  category?: Category | "all"; // "etc"는 기타 칩(연구·시험·기타)
  sort?: "deadline" | "recent";
}

// 화면의 오늘(KST "YYYY-MM-DD")과 지금. 목 모드는 목데이터의 기준 시각(2026-10-05)을 쓴다
export function todayKst(): string {
  return USE_MOCKS ? mockToday : getKstDateKey(new Date());
}

export function nowIso(): string {
  return USE_MOCKS ? mockNow : new Date().toISOString();
}

export type PosterPreviewState =
  | { status: "idle"; result: null }
  | { status: "failure"; result: null }
  | { status: "limit"; result: null }
  | { status: "duplicate"; result: PosterExtractResult };

// "기타" 칩은 연구·시험·기타 세 카테고리를 함께 고른다
function feedCategories(category: FeedParams["category"]): Category[] | null {
  if (!category || category === "all") return null;
  return category === "etc" ? ["research", "exam", "etc"] : [category];
}

const FEED_PAGE_SIZE = 50; // API 최대값
const FEED_MAX_PAGES = 20; // 1,000개까지 받는다. 더 있으면 next_cursor가 남는다

// GET /opportunities. 홈은 판정 결과를 모두 받아 화면에서 묶는다(지원 어려움은 맨 아래 묶음).
// 다음 쪽(next_cursor)이 없을 때까지 50개씩 이어 받는다. counts는 필터와 상관없는 전체 기준이다
export async function getFeed(params: FeedParams = {}): Promise<FeedResponse> {
  const categories = feedCategories(params.category);
  const sort = params.sort ?? "deadline";
  if (USE_MOCKS) return mock.getFeed(categories, sort);
  const query = new URLSearchParams({ sort, limit: String(FEED_PAGE_SIZE) });
  if (categories) query.set("category", categories.join(","));
  let page = await apiFetch<FeedResponse>(`/opportunities?${query}`);
  const items: OpportunityItem[] = [...page.items];
  for (let pages = 1; page.next_cursor && pages < FEED_MAX_PAGES; pages += 1) {
    query.set("cursor", page.next_cursor);
    page = await apiFetch<FeedResponse>(`/opportunities?${query}`);
    items.push(...page.items);
  }
  return { items, next_cursor: page.next_cursor, counts: page.counts };
}

// GET /opportunities/{id}. 서버가 지금 프로필로 다시 판정하고 조회 기록을 남긴다.
// 형식이 틀린 id(422, 예: 목 모드에서 쓰던 주소)도 없는 공고처럼 알린다
export async function getOpportunity(id: string): Promise<OpportunityDetail> {
  if (USE_MOCKS) return mock.getOpportunity(id);
  try {
    return await apiFetch<OpportunityDetail>(`/opportunities/${encodeURIComponent(id)}`);
  } catch (error) {
    if (error instanceof ApiError && error.code === "VALIDATION_FAILED") {
      throw new ApiError("NOT_FOUND", "공고를 찾을 수 없어요.", 404);
    }
    throw error;
  }
}

// 준비하기·서류 체크를 받을지. TODO(api): POST /opportunities/{id}/prepare·PATCH /planner/tasks가 생기면
// 아래 함수를 바꾸고 지운다. 그 전까지 실제 모드는 "준비 일정 만들기"를 누르면 준비 중이라고 알린다
export const PREPARE_READY = USE_MOCKS;
export const PREPARE_NOT_READY = "준비 일정 만들기는 아직 준비 중이에요. 지금은 필요 서류와 마감일을 이 화면에서 확인해 주세요.";

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

export function prepareOpportunity(
  id: string,
  includeCalendar: boolean,
  targetDate?: string,
): Promise<PrepareResult> {
  if (!PREPARE_READY) return notReady(PREPARE_NOT_READY);
  return respond(prepareStoredOpportunity(id, includeCalendar, targetDate));
}

// 서류 체크 = 플래너 할 일 완료 (PATCH /planner/tasks/{task_id})
export function setDocumentDone(
  opportunityId: string,
  documentId: string,
  isDone: boolean,
): Promise<OpportunityDetail> {
  if (!PREPARE_READY) return notReady("서류 체크는 아직 준비 중이에요.");
  return respond(setStoredDocumentDone(opportunityId, documentId, isDone));
}

// TODO(api): POST /opportunities/{id}/reports { reason, detail } — 신고(P1). 그 전까지 화면에 신고 버튼이 없다
export function reportOpportunity(
  _id: string,
  _reason: ReportReason,
  _detail: string,
): Promise<{ reported: boolean; hidden: boolean }> {
  return respond({ reported: true, hidden: false });
}

// 포스터 등록을 받을지. TODO(api): POST /files·/posters/extract·/posters/confirm(W6)이 생기면 아래 포스터 함수를
// 바꾸고 지운다. 그 전까지 실제 모드는 포스터 등록 화면에서 준비 중이라고 알린다(목 공고는 실제 상세에서 열리지 않는다)
export const POSTER_READY = USE_MOCKS;

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
