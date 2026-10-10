import { opportunityDetails } from "@/mocks/opportunityDetails";
import { opportunities } from "@/mocks/opportunities";
import { planner } from "@/mocks/planner";
import { mockToday } from "@/mocks/account";
import type {
  Condition,
  OpportunityItem,
  PosterExtractResult,
  OpportunityDetail,
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

export function registerStoredPoster(
  draft: PosterExtractResult["draft"],
): OpportunityDetail {
  const id = `poster-${Date.now()}`;
  const conditions: Condition[] = draft.requirements.map((requirement, index) => ({
    requirement_id: `poster-requirement-${index}`,
    field: requirement.field,
    label: requirement.condition_text,
    operator: requirement.operator,
    value: requirement.value,
    user_value: "확인됨",
    condition_text: requirement.condition_text,
    user_value_text: "확인됨",
    outcome: "pass",
    evidence_text: requirement.evidence_text,
    is_ambiguous: requirement.is_ambiguous,
  }));
  const item: OpportunityItem = {
    id,
    title: draft.title,
    organizer: draft.organizer,
    category: draft.category,
    source_type: "poster",
    deadline_at: draft.deadline_at,
    d_day: draft.deadline_at ? 25 : null,
    easy_summary: draft.easy_summary,
    eligibility: {
      status: "eligible",
      display_status: "eligible",
      summary: "현재 입력한 조건을 충족해요.",
      missing_fields: [],
    },
    recommend_reason: "직접 등록한 포스터 공고예요.",
    needs_review: draft.low_confidence_fields.length > 0,
    uploader_masked: "김*지",
    course_name: null,
    prepared: false,
    is_new: true,
  };
  const detail: OpportunityDetail = {
    id,
    title: draft.title,
    organizer: draft.organizer,
    category: draft.category,
    source_type: "poster",
    original_url: null,
    poster_url: "/assets/mock-opportunity-poster.svg",
    easy_summary: draft.easy_summary,
    apply_start_at: draft.apply_start_at,
    deadline_at: draft.deadline_at,
    needs_review: draft.low_confidence_fields.length > 0,
    extraction_confidence: draft.extraction_confidence,
    uploader_masked: "김*지",
    course_name: null,
    eligibility: {
      status: "eligible",
      display_status: "eligible",
      summary: "현재 입력한 조건을 충족해요.",
      reason_text: null,
      missing_fields: [],
      conditions,
      evaluated_at: "2026-10-05T10:30:00+09:00",
    },
    documents: draft.documents.map((document, index) => ({
      id: `poster-document-${index}`,
      ...document,
      how_to: null,
      is_required: true,
      task_id: null,
      is_done: null,
    })),
    prep: {
      prepared: false,
      prep_plan_id: null,
      tasks_total: 0,
      tasks_done: 0,
      calendar_events: [],
    },
    process: {
      extraction: [
        { seq: 1, label: "포스터에서 글자·날짜 읽기", status: "succeeded", latency_ms: 380 },
        { seq: 2, label: "지원 자격 정리", status: "succeeded", latency_ms: 240 },
        { seq: 3, label: "내 프로필과 비교", status: "succeeded", latency_ms: 190 },
      ],
      evaluated_at: "2026-10-05T10:30:00+09:00",
      prepare_run_id: null,
    },
    reported_by_me: false,
  };
  opportunities.unshift(item);
  detailsState[id] = detail;
  return detail;
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
