import { mockToday } from "@/mocks/account";
import { opportunities } from "@/mocks/opportunities";
import type {
  AttachmentItem,
  Clause,
  Condition,
  DocumentItem,
  OpportunityDetail,
  OpportunityItem,
  ProcessStep,
} from "@/types/api";

// 공고 상세 목데이터 (API 명세 v0.4 5장 모양). 판정표 문구는 서버 판정 엔진의 문구를 흉내 낸다
const EVALUATED_AT = "2026-10-05T09:35:00+09:00";

function step(seq: number, tool: string, label: string, latency: number, note: string | null): ProcessStep {
  return { seq, tool, label, status: "succeeded", latency_ms: latency, chosen_by: "agent", note };
}

function extractionSteps(attachment: AttachmentItem | undefined): ProcessStep[] {
  const read = [step(1, "fetch_original", "공고 원문 페이지 읽기", 420, "본문에 지원 자격이 적혀 있어 원문을 읽음")];
  if (attachment) {
    read.push(step(2, "read_attachment_text", `첨부 '${attachment.file_name}' 읽기`, 910, "본문에 '첨부 참조'만 있어 첨부를 읽음"));
    if (attachment.extract_status === "failed") read[1].status = "failed";
  }
  return [...read, step(read.length + 1, "submit_requirements", "지원 자격 정리", 310, null)];
}

function condition(
  id: string,
  clauseNo: number,
  field: string,
  label: string,
  text: string,
  mine: string | null,
  outcome: Condition["outcome"],
  evidence: string,
  unknownReason: Condition["unknown_reason"] = null,
): Condition {
  return {
    requirement_id: id, clause_no: clauseNo, field, label, operator: "eq", value: text, user_value: mine,
    condition_text: text, user_value_text: mine, outcome, unknown_reason: unknownReason,
    evidence_text: evidence, is_ambiguous: unknownReason === "ambiguous",
  };
}

const CREDITS = "직전학기 12학점 이상 이수한 학생 (단, 4학년은 학년만 확인)";
const enrollment = condition("req-enrollment", 1, "enrollment_status", "학적 상태", "재학", "재학", "pass", "신청일 기준 재학생이어야 합니다.");
// 같은 묶음(clause 2)의 두 조건은 "다음 중 하나"다
const credits = condition("req-credit", 2, "credits_last_semester", "직전학기 이수학점", "12학점 이상", "18학점", "pass", CREDITS);
const fourthGrade = condition("req-grade", 2, "grade", "학년", "4학년", "3학년", "fail", CREDITS);
const gpaPass = condition("req-gpa", 3, "gpa_last_semester", "직전학기 평점", "3.5 이상", "3.80", "pass", "직전학기 평점 3.5 이상");
const gpaFail = condition("req-gpa", 3, "gpa_last_semester", "직전학기 평점", "4.0 이상", "3.80", "fail", "직전학기 평점은 4.0 이상이어야 합니다.");
const team = condition("req-team", 4, "other", "기타 조건", "3인 이상 팀 구성", null, "unknown", "개인 또는 3인 이상 팀으로 참가할 수 있습니다.", "unsupported_field");
const detailRule = condition("req-detail-rule", 3, "other", "기타 조건", "세부 참가 자격", null, "unknown", "세부 참가 자격은 별도 공지를 따릅니다.", "ambiguous");

const missingConditions: Record<string, Condition> = {
  region: condition("req-region", 3, "region", "거주지역", "경기도 안산시", "경기도", "unknown", "안산시에 주민등록을 둔 청년", "missing_profile"),
  income_bracket: condition("req-income", 3, "income_bracket", "학자금 지원구간", "8구간 이하", null, "unknown", "학자금 지원구간 8구간 이하", "missing_profile"),
};

// 묶음 결과: 하나라도 충족이면 충족, 모두 불충족이면 불충족, 나머지는 모름 (판정엔진_규칙.md)
export function clausesOf(conditions: Condition[]): Clause[] {
  const groups = new Map<number, Condition[]>();
  for (const row of conditions) groups.set(row.clause_no, [...(groups.get(row.clause_no) ?? []), row]);
  return [...groups].map(([clauseNo, rows]) => ({
    clause_no: clauseNo,
    outcome: rows.some((row) => row.outcome === "pass") ? "pass" : rows.every((row) => row.outcome === "fail") ? "fail" : "unknown",
    condition_count: rows.length,
  }));
}

function conditionsFor(item: OpportunityItem): Condition[] {
  const base = [enrollment, credits, fourthGrade];
  if (item.eligibility.display_status === "ineligible") return [...base, gpaFail, team];
  if (item.eligibility.display_status === "missing_info") {
    return [...base, ...item.eligibility.missing_fields.map((field) => missingConditions[field])];
  }
  if (item.eligibility.display_status === "needs_review") return [...base, detailRule];
  return [...base, gpaPass];
}

function attachmentsFor(item: OpportunityItem): AttachmentItem[] {
  if (item.source_type !== "school_notice" && item.source_type !== "lms_announcement") return [];
  const failed = item.eligibility.display_status === "needs_review";
  return [{
    id: `att-${item.id}`,
    file_name: failed ? "모집 요강.pdf" : "신청서 양식.hwp",
    source_url: `https://example.edu/files/${item.id}`,
    extract_status: failed ? "failed" : "succeeded",
  }];
}

const preparedDocuments: DocumentItem[] = [
  { id: "doc-enrollment", name: "재학증명서", issuer: "HY-in", how_to: "HY-in 증명발급 메뉴에서 발급", lead_days: 0, effort_minutes: null, form_url: null, is_required: true, task_id: "task-student-cert", is_done: true },
  { id: "doc-grade", name: "성적증명서", issuer: "HY-in", how_to: "HY-in 증명발급 메뉴에서 발급", lead_days: 2, effort_minutes: null, form_url: null, is_required: true, task_id: "task-grade-cert", is_done: false },
  { id: "doc-application", name: "장학금 신청서", issuer: "ERICA 학생지원팀", how_to: "양식을 내려받아 작성", lead_days: null, effort_minutes: 30, form_url: "https://example.edu/forms/scholarship-2026", is_required: true, task_id: "task-application", is_done: false },
];

function makeDetail(item: OpportunityItem): OpportunityDetail {
  const prepared = item.id === "hanyang-support-2026";
  const conditions = conditionsFor(item);
  const attachments = attachmentsFor(item);
  const failedAttachment = attachments.find((attachment) => attachment.extract_status === "failed");
  return {
    id: item.id,
    title: item.title,
    organizer: item.organizer,
    category: item.category,
    source_type: item.source_type,
    status: "active",
    original_url: item.source_type === "poster" ? null : "https://example.edu/notices/" + item.id,
    poster_url: item.source_type === "poster" ? "/assets/mock-opportunity-poster.svg" : null,
    easy_summary: item.easy_summary,
    apply_start_at: "2026-09-20T09:00:00+09:00",
    deadline_at: item.deadline_at,
    needs_review: item.needs_review,
    review_reasons: item.needs_review
      ? [...(failedAttachment ? [`첨부 '${failedAttachment.file_name}'을 읽지 못했어요.`] : []), "AI 메모: 세부 참가 자격이 원문에 따로 적혀 있어요."]
      : [],
    extraction_confidence: item.source_type === "poster" ? 0.84 : 0.97,
    uploaded_by_me: item.uploaded_by_me,
    course_name: item.course_name,
    attachments,
    eligibility: {
      status: item.eligibility.status,
      display_status: item.eligibility.display_status,
      reason_text: item.eligibility.summary,
      basis_date: item.deadline_at ? item.deadline_at.slice(0, 10) : mockToday,
      requirements_version: 1,
      missing_fields: item.eligibility.missing_fields,
      clauses: clausesOf(conditions),
      conditions,
      evaluated_at: EVALUATED_AT,
    },
    documents: prepared ? preparedDocuments : preparedDocuments.map((document) => ({ ...document, task_id: null, is_done: null })),
    prep: {
      prepared,
      prep_plan_id: prepared ? "prep-hanyang-support" : null,
      tasks_total: prepared ? 4 : 0,
      tasks_done: prepared ? 1 : 0,
      calendar_events: prepared ? [{ id: "gcal-hanyang", provider: "google" }] : [],
    },
    process: {
      extraction: extractionSteps(attachments[0]),
      evaluated_at: EVALUATED_AT,
      prepare_run_id: prepared ? "run-prepare-hanyang" : null,
    },
    reported_by_me: false,
  };
}

export const opportunityDetails: Record<string, OpportunityDetail> = Object.fromEntries(
  opportunities.map((item) => [item.id, makeDetail(item)]),
);
