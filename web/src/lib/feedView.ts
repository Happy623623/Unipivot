import type { SummaryFilter } from "@/components/FeedSummary";
import type { FeedTab } from "@/components/FeedTabs";
import type { OpportunityItem } from "@/types/api";

// 홈 목록의 이름. 카테고리·요약 카드 거르기·정렬·탭이 같으면 같은 목록이다(바뀌면 1쪽부터 본다)
export function feedListKey(category: string, summaryFilter: SummaryFilter | null, sort: string | undefined, tab: FeedTab): string {
  return `${category}-${summaryFilter}-${sort}-${tab}`;
}

// 홈 목록 나누기(F-40·F-45). 추천 공고는 숨긴 공고를 뺀 전부, 관심·숨김은 그 표시를 한 공고만 보인다.
// 요약 카드로 거른 뒤 지원 어려움은 탭마다 목록 맨 아래 "지원 어려움 N개" 묶음(ineligible)으로 뗀다
export function feedView(items: OpportunityItem[], tab: FeedTab, summaryFilter: SummaryFilter | null) {
  const tabItems = items.filter((item) =>
    tab === "recommended" ? item.my_mark !== "not_interested" : item.my_mark === tab,
  );
  const filtered = tabItems.filter((item) => {
    if (summaryFilter === "eligible") return item.eligibility.display_status === "eligible";
    if (summaryFilter === "undetermined") return item.eligibility.status === "undetermined";
    if (summaryFilter === "deadline_soon") {
      return item.eligibility.status !== "ineligible" && item.d_day !== null && item.d_day >= 0 && item.d_day <= 3;
    }
    return true;
  });
  return {
    tabItems,
    visible: filtered.filter((item) => item.eligibility.display_status !== "ineligible"),
    ineligible: filtered.filter((item) => item.eligibility.display_status === "ineligible"),
  };
}
