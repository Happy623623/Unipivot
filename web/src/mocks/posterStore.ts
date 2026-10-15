import { mockToday } from "@/mocks/account";
import { clausesOf } from "@/mocks/opportunityDetails";
import { addStoredOpportunity } from "@/mocks/store";
import type {
  Condition,
  OpportunityDetail,
  OpportunityItem,
  PosterExtractResult,
  ProcessStep,
} from "@/types/api";

const EVALUATED_AT = "2026-10-05T10:30:00+09:00";

function step(seq: number, tool: string, label: string, latency: number): ProcessStep {
  return { seq, tool, label, status: "succeeded", latency_ms: latency, chosen_by: "pipeline", note: null };
}

// 목 모드의 포스터 등록 (POST /posters/confirm 흉내). 포스터 공고는 올린 사람에게만 보인다(uploaded_by_me)
export function registerStoredPoster(
  draft: PosterExtractResult["draft"],
): OpportunityDetail {
  const id = `poster-${Date.now()}`;
  const conditions: Condition[] = draft.requirements.map((requirement, index) => ({
    requirement_id: `poster-requirement-${index}`,
    clause_no: index + 1,
    field: requirement.field,
    label: "", // 포스터 추출 결과에는 항목 이름이 없어 조건 문구만 보여 준다
    operator: requirement.operator,
    value: requirement.value,
    user_value: "확인됨",
    condition_text: requirement.condition_text,
    user_value_text: "확인됨",
    outcome: "pass",
    unknown_reason: null,
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
      summary: "모든 조건 충족",
      missing_fields: [],
    },
    recommend_reason: "직접 등록한 포스터 공고예요.",
    needs_review: draft.low_confidence_fields.length > 0,
    uploaded_by_me: true,
    course_name: null,
    prepared: false,
    is_new: true,
    my_mark: null,
  };
  const detail: OpportunityDetail = {
    id,
    title: draft.title,
    organizer: draft.organizer,
    category: draft.category,
    source_type: "poster",
    status: "active",
    original_url: null,
    poster_url: "/assets/mock-opportunity-poster.svg",
    easy_summary: draft.easy_summary,
    apply_start_at: draft.apply_start_at,
    deadline_at: draft.deadline_at,
    needs_review: draft.low_confidence_fields.length > 0,
    review_reasons: draft.low_confidence_fields.length > 0 ? ["포스터에서 일부 글자를 또렷하게 읽지 못했어요."] : [],
    extraction_confidence: draft.extraction_confidence,
    uploaded_by_me: true,
    course_name: null,
    attachments: [],
    eligibility: {
      status: "eligible",
      display_status: "eligible",
      reason_text: "모든 조건 충족",
      basis_date: draft.deadline_at ? draft.deadline_at.slice(0, 10) : mockToday,
      requirements_version: 1,
      missing_fields: [],
      clauses: clausesOf(conditions),
      conditions,
      evaluated_at: EVALUATED_AT,
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
      // 실제 추출은 Vision 한 번이라 단계도 하나다(api/app/posters/service.py)
      extraction: [step(1, "submit_poster", "포스터에서 글자·날짜 읽기", 8100)],
      evaluated_at: EVALUATED_AT,
      prepare_run_id: null,
    },
    reported_by_me: false,
    my_mark: null,
  };
  addStoredOpportunity(item, detail);
  return detail;
}
