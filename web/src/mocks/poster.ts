import type { PosterExtractResult } from "@/types/api";

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
      { field: "enrollment_status", operator: "eq", value: "enrolled", condition_text: "전국 대학생 누구나", evidence_text: "공고일 기준 대학 재학생 및 휴학생", is_ambiguous: false },
      { field: "team_size", operator: "between", value: [1, 4], condition_text: "개인 또는 4인 이하 팀", evidence_text: "개인 및 4인 이하 팀으로 참가할 수 있습니다.", is_ambiguous: false },
      { field: "region_sido", operator: "any", value: null, condition_text: "지역 제한 없음", evidence_text: "전국 소재 대학생을 대상으로 합니다.", is_ambiguous: false },
    ],
    documents: [
      { name: "참가 신청서", issuer: "○○도시공사", lead_days: null, effort_minutes: 30, form_url: "https://example.edu/forms/city-contest" },
      { name: "아이디어 제안서", issuer: null, lead_days: null, effort_minutes: 90, form_url: null },
      { name: "재학증명서", issuer: "소속 대학", lead_days: 0, effort_minutes: null, form_url: null },
    ],
    extraction_confidence: 0.82,
    low_confidence_fields: ["organizer", "apply_start_at"],
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
