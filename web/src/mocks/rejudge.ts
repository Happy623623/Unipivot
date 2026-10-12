import { mockNow } from "@/mocks/account";
import { opportunities } from "@/mocks/opportunities";
import { clausesOf } from "@/mocks/opportunityDetails";
import { getStoredOpportunity } from "@/mocks/store";
import type { Condition, OpportunityDetail, Profile } from "@/types/api";

// 목 모드의 다시 판정. 실제 모드는 서버가 공고 상세를 줄 때 지금 프로필로 판정한다.
// "정보 필요" 공고에서 비어 있던 항목이 모두 채워지면 그 조건을 충족으로 바꾼다
const PROFILE_KEYS: Record<string, (keyof Profile)[]> = {
  age: ["birth_date"],
  region: ["region_sido", "region_sigungu"],
};

function filledValue(field: string, profile: Profile): string | null {
  const values = (PROFILE_KEYS[field] ?? [field as keyof Profile]).map((key) => profile[key]);
  if (values.some((value) => value === null || value === undefined || value === "")) return null;
  return values.join(" ");
}

export function rejudgeStoredOpportunity(id: string, profile: Profile): OpportunityDetail | undefined {
  const detail = getStoredOpportunity(id);
  if (!detail || detail.eligibility.display_status !== "missing_info") return detail;
  const eligibility = detail.eligibility;
  const filled = new Map(eligibility.missing_fields.map((field) => [field, filledValue(field, profile)]));
  if ([...filled.values()].some((value) => value === null)) return detail;

  eligibility.conditions = eligibility.conditions.map((row): Condition => {
    const value = filled.get(row.field);
    if (row.unknown_reason !== "missing_profile" || !value) return row;
    return { ...row, user_value: value, user_value_text: value, outcome: "pass", unknown_reason: null };
  });
  eligibility.status = "eligible";
  eligibility.display_status = "eligible";
  eligibility.reason_text = "모든 조건 충족";
  eligibility.missing_fields = [];
  eligibility.clauses = clausesOf(eligibility.conditions);
  eligibility.evaluated_at = mockNow;
  detail.process.evaluated_at = mockNow;
  const item = opportunities.find((entry) => entry.id === id);
  if (item) {
    item.eligibility = { status: "eligible", display_status: "eligible", summary: "모든 조건 충족", missing_fields: [] };
  }
  return detail;
}
