import { ApiError, apiFetch, USE_MOCKS, waitForRun } from "@/api/http";
import * as mock from "@/api/mockClient";
import { MockApiError, respond } from "@/api/mockClient";
import { getKstDateKey } from "@/lib/format";
import { mockNow, mockToday } from "@/mocks";
import {
  getStoredPlanner,
  addStoredManualTask,
  deleteStoredManualTask,
  addStoredCalendarEvent,
  moveStoredTask,
  prepareStoredOpportunity,
  removeStoredCalendarEvent,
  setStoredPlannerTaskDone,
  setStoredDocumentDone,
  updateStoredManualTask,
} from "@/mocks/store";
import type {
  CalendarEvent,
  Category,
  FeedResponse,
  MarkResult,
  OpportunityDetail,
  OpportunityItem,
  OpportunityMark,
  PlannerResponse,
  PlannerTask,
  PrepareResult,
  PrepareStarted,
  ProcessStep,
  ReportReason,
} from "@/types/api";

// 화면이 쓰는 데이터 함수는 모두 이 파일에서 가져간다.
// 계정·LMS·포스터 함수는 accountClient.ts·lmsClient.ts·posterClient.ts에 두고 여기서 다시 내보낸다.
// 공고 피드·상세·준비하기는 실제 API를 부르고, 아래 플래너 함수는 아직 목이다
export * from "@/api/accountClient";
export * from "@/api/lmsClient";
export * from "@/api/posterClient";
export * from "@/api/pushClient";
export * from "@/api/syllabusClient";
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

// "기타" 칩은 연구·시험·기타 세 카테고리를 함께 고른다
function feedCategories(category: FeedParams["category"]): Category[] | null {
  if (!category || category === "all") return null;
  return category === "etc" ? ["research", "exam", "etc"] : [category];
}

const FEED_PAGE_SIZE = 50; // API 최대값
const FEED_MAX_PAGES = 20; // 1,000개까지 받는다. 더 있으면 next_cursor가 남는다

// GET /opportunities. 홈은 판정 결과를 모두 받아 화면에서 묶는다(지원 어려움은 맨 아래 묶음, 추천·관심·숨김 탭).
// 숨김 탭을 위해 관심 없음 공고도 받고(include_not_interested), 다음 쪽(next_cursor)이 없을 때까지 50개씩
// 이어 받는다. counts는 필터와 상관없는 전체 기준이고 관심 없음 공고는 세지 않는다
export async function getFeed(params: FeedParams = {}): Promise<FeedResponse> {
  const categories = feedCategories(params.category);
  const sort = params.sort ?? "deadline";
  if (USE_MOCKS) return mock.getFeed(categories, sort, true);
  const query = new URLSearchParams({ sort, limit: String(FEED_PAGE_SIZE), include_not_interested: "true" });
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

// PUT·DELETE /opportunities/{id}/mark (F-45). 관심·관심 없음 표시를 바꾸고, null이면 지운다
export async function setOpportunityMark(id: string, mark: OpportunityMark | null): Promise<void> {
  if (USE_MOCKS) return mock.setOpportunityMark(id, mark);
  const path = `/opportunities/${encodeURIComponent(id)}/mark`;
  if (mark === null) await apiFetch<void>(path, { method: "DELETE" });
  else await apiFetch<MarkResult>(path, { method: "PUT", body: JSON.stringify({ mark }) });
}


// GET /planner/tasks (F-43). 기간 안의 할 일과 마커(준비 중인 공고의 마감일). 날짜는 KST다
export function getPlanner(from: string, to: string): Promise<PlannerResponse> {
  if (USE_MOCKS) {
    const storedPlanner = getStoredPlanner();
    return respond({
      items: storedPlanner.items.filter((item) => item.due_date >= from && item.due_date <= to),
      markers: storedPlanner.markers.filter((marker) => marker.date >= from && marker.date <= to),
    });
  }
  const query = new URLSearchParams({ from, to });
  return apiFetch<PlannerResponse>(`/planner/tasks?${query}`);
}

// PATCH /planner/tasks/{id}. 완료 체크는 어느 출처든 할 수 있다
export function setPlannerTaskDone(id: string, isDone: boolean): Promise<PlannerTask> {
  if (USE_MOCKS) return respond(setStoredPlannerTaskDone(id, isDone));
  return patchTask(id, { is_done: isDone });
}

export function addManualPlannerTask(title: string, dueDate: string): Promise<PlannerTask> {
  if (USE_MOCKS) return respond(addStoredManualTask(title, dueDate));
  return apiFetch<PlannerTask>("/planner/tasks", {
    method: "POST",
    body: JSON.stringify({ title, due_date: dueDate }),
  });
}

// 직접 추가한 할 일만 제목까지 고친다
export function updateManualPlannerTask(id: string, title: string, dueDate: string): Promise<PlannerTask> {
  if (USE_MOCKS) return respond(updateStoredManualTask(id, title, dueDate));
  return patchTask(id, { title, due_date: dueDate });
}

// 준비·강의계획서 할 일은 날짜만 옮긴다(제목은 공고의 서류 이름이라 고정)
export function movePlannerTask(id: string, dueDate: string): Promise<PlannerTask> {
  if (USE_MOCKS) return respond(moveStoredTask(id, dueDate));
  return patchTask(id, { due_date: dueDate });
}

export function deleteManualPlannerTask(id: string): Promise<void> {
  if (USE_MOCKS) {
    deleteStoredManualTask(id);
    return respond(undefined);
  }
  return apiFetch<void>(`/planner/tasks/${encodeURIComponent(id)}`, { method: "DELETE" });
}

function patchTask(id: string, body: Record<string, unknown>): Promise<PlannerTask> {
  return apiFetch<PlannerTask>(`/planner/tasks/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

// POST /calendar/events (F-32). 준비한 공고의 마감일을 Google 캘린더에 넣는다.
// 이미 넣었으면 서버가 그 일정을 그대로 준다(중복 등록 없음)
export function registerCalendarEvent(opportunityId: string): Promise<CalendarEvent> {
  if (USE_MOCKS) return respond(addStoredCalendarEvent(opportunityId));
  return apiFetch<CalendarEvent>("/calendar/events", {
    method: "POST",
    body: JSON.stringify({ provider: "google", opportunity_id: opportunityId }),
  });
}

// DELETE /calendar/events/{id}. Google 캘린더에서도 지운다
export function removeCalendarEvent(eventId: string): Promise<void> {
  if (USE_MOCKS) {
    removeStoredCalendarEvent(eventId);
    return respond(undefined);
  }
  return apiFetch<void>(`/calendar/events/${encodeURIComponent(eventId)}`, { method: "DELETE" });
}

export interface PrepareOptions {
  force?: boolean; // 지원 어려움 공고를 "그래도 준비하기"로 다시 보낸다
  onProgress?: (steps: ProcessStep[]) => void; // 실행 단계(GET /runs/{id}의 steps)
}

// POST /opportunities/{id}/prepare → 202 run_id → GET /runs/{id}로 끝날 때까지 기다린다(API 명세 2·7장).
// 이미 준비한 공고는 200이고, 그 실행이 남아 있지 않으면 결과도 없다(null: 부른 쪽이 상세를 다시 받는다)
export async function prepareOpportunity(
  id: string,
  targetDate?: string,
  options: PrepareOptions = {},
): Promise<PrepareResult | null> {
  if (USE_MOCKS) return respond(prepareStoredOpportunity(id, targetDate));
  const started = await apiFetch<PrepareStarted>(
    `/opportunities/${encodeURIComponent(id)}/prepare`,
    {
      method: "POST",
      body: JSON.stringify({
        ...(targetDate ? { target_date: targetDate } : {}),
        ...(options.force ? { force: true } : {}),
      }),
    },
  );
  if (!started.run_id) return null; // 실행 기록이 지워진 옛 계획. 상세로 보여 준다
  const run = await waitForRun<PrepareResult>(started.run_id, (current) =>
    options.onProgress?.(current.steps),
  );
  if (run.status === "failed") {
    const error = run.error;
    throw new ApiError(
      error?.code ?? "INTERNAL_ERROR",
      error?.message ?? "준비 일정을 만들지 못했어요. 잠시 후 다시 눌러 주세요.",
      0,
    );
  }
  return run.result;
}

// 서류 체크 = 그 서류의 플래너 할 일 완료 (PATCH /planner/tasks/{task_id}).
// 준비하기 전에는 할 일이 없어 taskId가 null이고, 화면이 체크를 막는다
export async function setDocumentDone(
  opportunityId: string,
  taskId: string,
  isDone: boolean,
): Promise<OpportunityDetail> {
  if (USE_MOCKS) return respond(setStoredDocumentDone(opportunityId, taskId, isDone));
  await setPlannerTaskDone(taskId, isDone);
  return getOpportunity(opportunityId); // 진행률(tasks_done)을 서버 값으로 다시 받는다
}

// TODO(api): POST /opportunities/{id}/reports { reason, detail } — 신고(P1). 그 전까지 화면에 신고 버튼이 없다
export function reportOpportunity(
  _id: string,
  _reason: ReportReason,
  _detail: string,
): Promise<{ reported: boolean; hidden: boolean }> {
  return respond({ reported: true, hidden: false });
}
