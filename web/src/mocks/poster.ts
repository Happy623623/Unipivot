import type { PosterExtractResult } from "@/types/api";

// 실제 추출 결과와 같은 모양이다. 요건 항목·연산자는 판정 엔진이 아는 것만 쓴다(docs/판정엔진_규칙.md)
export const posterExtractResult: PosterExtractResult = {
  kind: "poster_extract",
  draft: {
    title: "2026 대학생 도시 아이디어 공모전",
    organizer: "○○도시공사",
    category: "contest",
    apply_start_at: "2026-10-01T09:00:00+09:00",
    deadline_at: "2026-10-30T23:59:00+09:00",
    easy_summary: "도시 문제 해결 아이디어를 제안하는 전국 대학생 대상 공모전이에요.",
    requirements: [
      { clause_no: 1, field: "enrollment_status", operator: "in", value: ["enrolled", "on_leave"], basis: null, condition_text: "재학 또는 휴학", evidence_text: "공고일 기준 대학 재학생 및 휴학생", is_ambiguous: false },
      { clause_no: 2, field: "degree_program", operator: "eq", value: "bachelor", basis: null, condition_text: "학부", evidence_text: "학부 재학생을 대상으로 합니다.", is_ambiguous: false },
      { clause_no: 3, field: "other", operator: "eq", value: { text: "개인 또는 4인 이하 팀" }, basis: null, condition_text: "개인 또는 4인 이하 팀", evidence_text: "개인 및 4인 이하 팀으로 참가할 수 있습니다.", is_ambiguous: true },
    ],
    documents: [
      { name: "참가 신청서", issuer: "공고 첨부 양식·신청 사이트", lead_days: 0, effort_minutes: 30, form_url: "https://example.edu/forms/city-contest" },
      { name: "아이디어 제안서", issuer: null, lead_days: null, effort_minutes: null, form_url: null },
      { name: "재학증명서", issuer: "한양인 포털", lead_days: 0, effort_minutes: null, form_url: null },
    ],
    extraction_confidence: 0.82,
    low_confidence_fields: ["organizer", "apply_start_at", "requirements"],
  },
  duplicate_candidate: null,
};

export const duplicatePosterExtractResult: PosterExtractResult = {
  ...posterExtractResult,
  duplicate_candidate: {
    opportunity_id: "city-idea-contest",
    title: "2026 대학생 도시 아이디어 공모전",
  },
};
