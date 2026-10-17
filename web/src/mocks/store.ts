import { opportunityDetails } from "@/mocks/opportunityDetails";
import { opportunities } from "@/mocks/opportunities";
import { planner } from "@/mocks/planner";
import { mockToday } from "@/mocks/account";
import type {
  CalendarEvent,
  OpportunityItem,
  OpportunityDetail,
  OpportunityMark,
  PlannerResponse,
  PlannerTask,
  PrepareResult,
} from "@/types/api";

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

const detailsState = clone(opportunityDetails);
const plannerState = clone(planner);
// 마감일 캘린더 등록(F-32). 메모리에만 있어 새로고침하면 사라진다
const calendarState: { opportunity_id: string; event: CalendarEvent }[] = [];

function subtractDays(date: string, days: number): string {
  const value = new Date(`${date.slice(0, 10)}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() - days);
  return value.toISOString().slice(0, 10);
}

// 역산한 날짜가 오늘보다 앞서면 오늘로 당긴다 (API v0.3 보완 규칙)
function clampToToday(date: string): string {
  return date < mockToday ? mockToday : date;
}

function tasksForOpportunity(opportunityId: string): PlannerTask[] {
  return plannerState.items.filter(
    (task) => task.source === "prep_plan" && task.link.id === opportunityId,
  );
}

export function getStoredOpportunity(id: string): OpportunityDetail | undefined {
  return detailsState[id];
}

export function getStoredPlanner(): PlannerResponse {
  return plannerState;
}

export function prepareStoredOpportunity(id: string, targetDate?: string): PrepareResult {
  const detail = detailsState[id];
  if (!detail) throw new Error("공고를 찾을 수 없어요.");

  // 상시 공고는 사용자가 고른 목표일을 마감일처럼 쓴다
  const deadline = detail.deadline_at?.slice(0, 10) ?? targetDate ?? mockToday;
  const prepPlanId = detail.prep.prep_plan_id ?? `prep-${id}`;

  if (!detail.prep.prepared) {
    const documentTasks: PlannerTask[] = detail.documents.map((document) => {
      const taskId = `task-${id}-${document.id}`;
      document.task_id = taskId;
      document.is_done = false;
      return {
        id: taskId,
        title: `${document.name} 준비`,
        // 마감 2일 전까지 서류를 갖추도록 발급 소요일만큼 앞당긴다(모르면 하루, API와 같다)
        due_date: clampToToday(subtractDays(deadline, 2 + (document.lead_days ?? 1))),
        is_done: false,
        source: "prep_plan",
        link: {
          type: "opportunity",
          id,
          title: detail.title,
          category: detail.category,
        },
      };
    });
    const submitTask: PlannerTask = {
      id: `task-${id}-submit`,
      title: "신청 제출",
      due_date: clampToToday(subtractDays(deadline, 1)), // 신청은 마감 하루 전에 낸다
      is_done: false,
      source: "prep_plan",
      link: {
        type: "opportunity",
        id,
        title: detail.title,
        category: detail.category,
      },
    };
    plannerState.items.push(...documentTasks, submitTask);
    if (detail.deadline_at && !plannerState.markers.some((marker) => marker.opportunity_id === id)) {
      plannerState.markers.push({
        kind: "deadline",
        date: deadline,
        title: `${detail.title} 마감`,
        opportunity_id: id,
        category: detail.category,
      });
    }
    const feedItem = opportunities.find((item) => item.id === id);
    if (feedItem) feedItem.prepared = true;
  }

  const tasks = tasksForOpportunity(id);
  detail.prep = {
    prepared: true,
    prep_plan_id: prepPlanId,
    tasks_total: tasks.length,
    tasks_done: tasks.filter((task) => task.is_done).length,
    calendar_events: detail.prep.calendar_events ?? [], // 캘린더는 따로 등록한다(F-32)
  };
  detail.process.prepare_run_id = `run-prepare-${id}`;

  return {
    kind: "prepare",
    prep_plan_id: prepPlanId,
    documents: detail.documents,
    tasks: tasks.map((task) => ({
      id: task.id,
      title: task.title,
      due_date: task.due_date,
      document_id:
        detail.documents.find((document) => document.task_id === task.id)?.id ?? null,
    })),
    calendar_event: null, // 마감일 캘린더는 준비하기와 따로 등록한다(F-32)
    calendar_error: null,
  };
}

// 마감일 캘린더 등록(F-32). 준비한 공고만 넣고, 같은 공고를 다시 넣어도 하나다
export function addStoredCalendarEvent(opportunityId: string): CalendarEvent {
  const detail = detailsState[opportunityId];
  if (!detail) throw new Error("공고를 찾을 수 없어요.");
  if (!detail.prep.prepared) throw new Error("준비 일정을 먼저 만들어 주세요.");
  if (!detail.deadline_at) throw new Error("마감일이 없는 공고예요. 캘린더에 넣을 수 없어요.");
  const existing = calendarState.find((event) => event.opportunity_id === opportunityId);
  if (existing) return existing.event;
  const ends = new Date(detail.deadline_at);
  const event: CalendarEvent = {
    id: `gcal-${opportunityId}`,
    provider: "google",
    external_event_id: `ext-${opportunityId}`,
    title: `[마감] ${detail.title}`,
    starts_at: new Date(ends.getTime() - 60 * 60 * 1000).toISOString(),
    all_day: false,
  };
  calendarState.push({ opportunity_id: opportunityId, event });
  detail.prep.calendar_events = [{ id: event.id, provider: "google" }];
  return event;
}

export function removeStoredCalendarEvent(eventId: string): void {
  const index = calendarState.findIndex((entry) => entry.event.id === eventId);
  if (index < 0) throw new Error("캘린더 일정을 찾을 수 없어요.");
  const [removed] = calendarState.splice(index, 1);
  const detail = detailsState[removed.opportunity_id];
  if (detail) detail.prep.calendar_events = [];
}

// 준비·강의계획서 할 일 옮기기(날짜만). 직접 추가한 할 일은 updateStoredManualTask가 제목까지 고친다.
// LMS 할 일은 완료만 바꿀 수 있어 실제 API처럼 막는다(API 명세 7장)
export function moveStoredTask(id: string, dueDate: string): PlannerTask {
  const task = plannerState.items.find((item) => item.id === id);
  if (!task) throw new Error("할 일을 찾을 수 없어요.");
  if (task.source === "lms_assignment" || task.source === "lms_announcement") {
    throw new Error("LMS에서 가져온 할 일은 완료만 바꿀 수 있어요.");
  }
  task.due_date = dueDate;
  return task;
}

export function setStoredDocumentDone(
  opportunityId: string,
  taskId: string,
  isDone: boolean,
): OpportunityDetail {
  const detail = detailsState[opportunityId];
  if (!detail) throw new Error("공고를 찾을 수 없어요.");
  const document = detail.documents.find((item) => item.task_id === taskId);
  if (!document) throw new Error("준비 일정을 먼저 만들어 주세요.");

  document.is_done = isDone;
  const task = plannerState.items.find((item) => item.id === taskId);
  if (task) task.is_done = isDone;
  const tasks = tasksForOpportunity(opportunityId);
  detail.prep.tasks_done = tasks.filter((item) => item.is_done).length;
  detail.prep.tasks_total = tasks.length;
  return detail;
}

// 관심·숨김 표시(F-45). 피드 항목과 상세에 같이 적어, 상세를 다시 받아도(서류 체크·다시 판정) 표시가 남는다.
// 없는 공고면 false. 메모리에만 있어 새로고침하면 표시가 없는 목데이터로 돌아간다
export function setStoredMark(id: string, mark: OpportunityMark | null): boolean {
  const item = opportunities.find((entry) => entry.id === id);
  const detail = detailsState[id];
  if (item) item.my_mark = mark;
  if (detail) detail.my_mark = mark;
  return Boolean(item ?? detail);
}

// 포스터 등록(posterStore.ts)이 만든 공고를 피드 맨 앞과 상세에 넣는다
export function addStoredOpportunity(item: OpportunityItem, detail: OpportunityDetail): void {
  opportunities.unshift(item);
  detailsState[detail.id] = detail;
}

export function setStoredPlannerTaskDone(
  taskId: string,
  isDone: boolean,
): PlannerTask {
  const task = plannerState.items.find((item) => item.id === taskId);
  if (!task) throw new Error("할 일을 찾을 수 없어요.");
  task.is_done = isDone;

  if (task.link.type === "opportunity" && task.link.id) {
    const detail = detailsState[task.link.id];
    const document = detail?.documents.find((item) => item.task_id === taskId);
    if (document) document.is_done = isDone;
    if (detail) {
      const tasks = tasksForOpportunity(detail.id);
      detail.prep.tasks_done = tasks.filter((item) => item.is_done).length;
    }
  }
  return task;
}

export function addStoredManualTask(
  title: string,
  dueDate: string,
): PlannerTask {
  const task: PlannerTask = {
    id: `manual-${Date.now()}`,
    title,
    due_date: dueDate,
    is_done: false,
    source: "manual",
    link: { type: null, id: null, title: null, category: null },
  };
  plannerState.items.push(task);
  return task;
}

// 계획서 일정을 확정했다(F-14). 같은 일정의 할 일은 하나이고, 체크를 풀면 지운다.
// 만들었으면 true다(실제 서버의 planner_tasks_created와 같은 뜻)
export function syncStoredSyllabusTask(
  itemId: string,
  title: string,
  dueDate: string,
  course: string | null,
  selected: boolean,
): boolean {
  const found = plannerState.items.find((task) => task.link.id === itemId);
  if (!selected) {
    if (found && !found.is_done) {
      plannerState.items = plannerState.items.filter((task) => task !== found);
    }
    return false;
  }
  if (found) {
    found.title = title;
    found.due_date = dueDate;
    return false;
  }
  plannerState.items.push({
    id: `syllabus-task-${itemId}`,
    title,
    due_date: dueDate,
    is_done: false,
    source: "syllabus",
    link: { type: "syllabus_item", id: itemId, title: course, category: null },
  });
  return true;
}

export function updateStoredManualTask(
  id: string,
  title: string,
  dueDate: string,
): PlannerTask {
  const task = plannerState.items.find((item) => item.id === id);
  if (!task || task.source !== "manual") {
    throw new Error("직접 추가한 일정만 수정할 수 있어요.");
  }
  task.title = title;
  task.due_date = dueDate;
  return task;
}

export function deleteStoredManualTask(id: string): void {
  const index = plannerState.items.findIndex(
    (item) => item.id === id && item.source === "manual",
  );
  if (index < 0) throw new Error("직접 추가한 일정을 찾을 수 없어요.");
  plannerState.items.splice(index, 1);
}
