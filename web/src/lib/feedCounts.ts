import type { FeedCounts, OpportunityItem, OpportunityMark } from "@/types/api";

// 홈 요약 카드 숫자 규칙(API 명세 5장 counts). 숨긴 공고를 빼거나 다시 넣을 때 화면에서 숫자를 고치고,
// 목 모드는 이 규칙으로 센다. 마감 임박은 지원 어려움을 빼고 D-3~D-day다. 규칙을 바꾸면
// api/tests/test_marks_db.py의 removed_from_counts도 같이 고친다(서버 SQL과 맞는지 그 테스트가 본다)
export const NO_COUNTS: FeedCounts = {
  eligible: 0, new_eligible: 0, undetermined: 0, missing_info: 0, needs_review: 0, ineligible: 0, deadline_soon: 0,
};

export function countDelta(counts: FeedCounts, item: OpportunityItem, sign: 1 | -1): FeedCounts {
  const { status, display_status: display } = item.eligibility;
  const soon = status !== "ineligible" && item.d_day !== null && item.d_day >= 0 && item.d_day <= 3;
  const add = (yes: boolean) => (yes ? sign : 0);
  return {
    eligible: counts.eligible + add(status === "eligible"),
    new_eligible: counts.new_eligible + add(status === "eligible" && item.is_new),
    undetermined: counts.undetermined + add(status === "undetermined"),
    missing_info: counts.missing_info + add(display === "missing_info"),
    needs_review: counts.needs_review + add(display === "needs_review"),
    ineligible: counts.ineligible + add(status === "ineligible"),
    deadline_soon: counts.deadline_soon + add(soon),
  };
}

export function countItems(items: OpportunityItem[]): FeedCounts {
  return items.reduce((counts, item) => countDelta(counts, item, 1), NO_COUNTS);
}

// 화면에서 바꾼 표시(marks)만큼 서버 숫자를 고친다. 서버가 준 표시(item.my_mark)와 숨김 여부가 다른 공고만
// 센다. 목록을 다시 받아 서버가 이미 반영했으면 고칠 것이 없다
export function adjustCounts(
  counts: FeedCounts,
  items: OpportunityItem[],
  marks: Readonly<Record<string, OpportunityMark | null>>,
): FeedCounts {
  return items.reduce((total, item) => {
    if (!(item.id in marks)) return total;
    const hidden = marks[item.id] === "not_interested";
    return hidden === (item.my_mark === "not_interested") ? total : countDelta(total, item, hidden ? -1 : 1);
  }, counts);
}
