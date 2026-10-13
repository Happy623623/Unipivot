import { opportunityDetails } from "@/mocks/opportunityDetails";
import { opportunities } from "@/mocks/opportunities";
import { planner } from "@/mocks/planner";
import { mockToday } from "@/mocks/account";
import type {
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

export function prepareStoredOpportunity(
  id: string,
  includeCalendar: boolean,
  targetDate?: string,
): PrepareResult {
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
        // 제출 2일 전까지 서류를 갖추도록 발급 소요일만큼 앞당긴다
        due_date: clampToToday(subtractDays(deadline, 2 + (document.lead_days ?? 0))),
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
      title: "신청서 제출",
      due_date: deadline,
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
    calendar_events:
      includeCalendar && detail.deadline_at
        ? [{ id: `gcal-${id}`, provider: "google" }]
        : [],
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
    calendar_event:
      includeCalendar && detail.deadline_at
        ? {
            id: `gcal-${id}`,
            provider: "google",
            starts_at: detail.deadline_at,
          }
        : null,
  };
}

export function setStoredDocumentDone(
  opportunityId: string,
  documentId: string,
  isDone: boolean,
): OpportunityDetail {
  const detail = detailsState[opportunityId];
  if (!detail) throw new Error("공고를 찾을 수 없어요.");
  const document = detail.documents.find((item) => item.id === documentId);
  if (!document?.task_id) throw new Error("준비 일정을 먼저 만들어 주세요.");

  document.is_done = isDone;
  const task = plannerState.items.find((item) => item.id === document.task_id);
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
