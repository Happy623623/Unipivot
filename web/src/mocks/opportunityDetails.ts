import { opportunities } from "@/mocks/opportunities";
import type {
  Condition,
  DocumentItem,
  OpportunityDetail,
  OpportunityItem,
  ProcessStep,
} from "@/types/api";

const extraction: ProcessStep[] = [
  { seq: 1, label: "공고 원문 읽기", status: "succeeded", latency_ms: 420 },
  { seq: 2, label: "요건 구조화", status: "succeeded", latency_ms: 310 },
  { seq: 3, label: "프로필 판정", status: "succeeded", latency_ms: 180 },
];

const mixedConditions: Condition[] = [
  { requirement_id: "req-enrollment", field: "enrollment_status", label: "재학생", operator: "eq", value: "enrolled", user_value: "enrolled", condition_text: "재학생만 지원 가능", user_value_text: "재학 중", outcome: "pass", evidence_text: "신청일 기준 재학생이어야 합니다.", is_ambiguous: false },
  { requirement_id: "req-credit", field: "credits_last_semester", label: "직전학기 취득학점", operator: "gte", value: 12, user_value: 18, condition_text: "직전학기 12학점 이상", user_value_text: "18학점", outcome: "pass", evidence_text: "직전학기 12학점 이상 이수한 학생을 대상으로 합니다.", is_ambiguous: false },
  { requirement_id: "req-gpa", field: "gpa_last_semester", label: "직전학기 평점", operator: "gte", value: 4, user_value: 3.8, condition_text: "직전학기 평점 4.0 이상", user_value_text: "3.80", outcome: "fail", evidence_text: "직전학기 평점은 4.0 이상이어야 합니다.", is_ambiguous: false },
  { requirement_id: "req-team", field: "other", label: "팀 구성", operator: "gte", value: 3, user_value: null, condition_text: "3인 이상 팀 구성", user_value_text: null, outcome: "unknown", evidence_text: "개인 또는 3인 이상 팀으로 참가할 수 있습니다.", is_ambiguous: true },
];

const passedConditions: Condition[] = mixedConditions.map((condition) => ({
  ...condition,
  user_value: condition.outcome === "fail" ? 4.2 : condition.outcome === "unknown" ? 4 : condition.user_value,
  user_value_text: condition.outcome === "fail" ? "4.20" : condition.outcome === "unknown" ? "4인 팀" : condition.user_value_text,
  outcome: "pass",
  is_ambiguous: false,
}));

const preparedDocuments: DocumentItem[] = [
  { id: "doc-enrollment", name: "재학증명서", issuer: "HY-in", how_to: "HY-in 증명발급 메뉴에서 발급", lead_days: 0, effort_minutes: null, form_url: null, is_required: true, task_id: "task-student-cert", is_done: true },
  { id: "doc-grade", name: "성적증명서", issuer: "HY-in", how_to: "HY-in 증명발급 메뉴에서 발급", lead_days: 2, effort_minutes: null, form_url: null, is_required: true, task_id: "task-grade-cert", is_done: false },
  { id: "doc-application", name: "장학금 신청서", issuer: "ERICA 학생지원팀", how_to: "양식을 내려받아 작성", lead_days: null, effort_minutes: 30, form_url: "https://example.edu/forms/scholarship-2026", is_required: true, task_id: "task-application", is_done: false },
];

function missingConditions(item: OpportunityItem): Condition[] {
  return item.eligibility.missing_fields.map((field, index) => ({
    requirement_id: `req-missing-${index}`,
    field,
    label: field === "region_sigungu" ? "거주 시군" : field === "income_bracket" ? "학자금 지원구간" : field,
    operator: "exists",
    value: true,
    user_value: null,
    condition_text: field === "region_sigungu" ? "경기도 내 거주" : "학자금 지원구간 확인",
    user_value_text: null,
    outcome: "unknown",
    evidence_text: "신청 자격 확인을 위해 해당 정보를 제출해야 합니다.",
    is_ambiguous: false,
  }));
}

function conditionsFor(item: OpportunityItem, prepared: boolean): Condition[] {
  if (prepared) return passedConditions;
  if (item.eligibility.display_status === "ineligible") return mixedConditions;
  if (item.eligibility.missing_fields.length > 0) {
    return [...passedConditions.slice(0, 2), ...missingConditions(item)];
  }
  if (item.needs_review) return [passedConditions[0], { ...mixedConditions[3], outcome: "unknown" }];
  return passedConditions;
}

function makeDetail(item: OpportunityItem): OpportunityDetail {
  const prepared = item.id === "hanyang-support-2026";
  return {
    id: item.id,
    title: item.title,
    organizer: item.organizer,
    category: item.category,
    source_type: item.source_type,
    original_url: "https://example.edu/notices/" + item.id,
    poster_url: item.source_type === "poster" ? "/assets/mock-opportunity-poster.svg" : null,
    easy_summary: item.easy_summary,
    apply_start_at: "2026-09-20T09:00:00+09:00",
    deadline_at: item.deadline_at,
    needs_review: item.needs_review,
    extraction_confidence: item.source_type === "poster" ? 0.84 : 0.97,
    uploader_masked: item.uploader_masked,
    course_name: item.course_name,
    eligibility: {
      status: item.eligibility.status,
      display_status: item.eligibility.display_status,
      summary: item.eligibility.summary,
      reason_text: item.eligibility.display_status === "ineligible" ? item.eligibility.summary : null,
      missing_fields: item.eligibility.missing_fields,
      conditions: conditionsFor(item, prepared),
      evaluated_at: "2026-10-05T09:35:00+09:00",
    },
    documents: prepared ? preparedDocuments : preparedDocuments.map((document) => ({ ...document, task_id: null, is_done: null })),
    prep: {
      prepared,
      prep_plan_id: prepared ? "prep-hanyang-support" : null,
      tasks_total: prepared ? 4 : 0,
      tasks_done: prepared ? 1 : 0,
      calendar_events: prepared ? [{ id: "gcal-hanyang", provider: "google" }] : [],
    },
    process: { extraction, evaluated_at: "2026-10-05T09:35:00+09:00", prepare_run_id: prepared ? "run-prepare-hanyang" : null },
    reported_by_me: false,
  };
}

export const opportunityDetails: Record<string, OpportunityDetail> = Object.fromEntries(
  opportunities.map((item) => [item.id, makeDetail(item)]),
);
