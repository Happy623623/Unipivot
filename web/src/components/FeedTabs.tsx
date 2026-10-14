import type { OpportunityMark } from "@/types/api";

// 홈 공고 목록 탭(F-45). 추천 공고는 숨긴 공고를 뺀 전부, 관심·숨김은 그 표시를 한 공고만이다.
// 관심·숨김 숫자는 지금 고른 카테고리 안에서 센다(0이면 숫자를 쓰지 않는다)
export type FeedTab = "recommended" | "interested" | "not_interested";

const feedTabs: { label: string; value: FeedTab; showLabel: string }[] = [
  { label: "추천 공고", value: "recommended", showLabel: "추천 공고 보기" },
  { label: "관심", value: "interested", showLabel: "관심 탭 보기" },
  { label: "숨김", value: "not_interested", showLabel: "숨김 탭 보기" },
];

// 표시를 바꿔 공고가 새로 들어가는 탭. 관심을 풀면 공고는 추천 공고에 그대로 있어 들어가는 탭이 없다
export function arrivalTab(before: OpportunityMark | null, next: OpportunityMark | null): FeedTab | null {
  if (next === "interested") return "interested";
  if (next === "not_interested") return "not_interested";
  return before === "not_interested" ? "recommended" : null;
}

// 안내에 붙이는 "그 탭 보기" 버튼 이름
export function showTabLabel(tab: FeedTab): string {
  return feedTabs.find((item) => item.value === tab)?.showLabel ?? "";
}

export interface TabArrival {
  tab: FeedTab;
  id: number; // 같은 탭에 이어 들어가도 강조를 다시 시작한다
}

interface FeedTabsProps {
  tab: FeedTab;
  counts: Record<Exclude<FeedTab, "recommended">, number>;
  arrived: TabArrival | null; // 방금 공고가 들어간 탭. 이름과 숫자를 잠깐 주색으로 키운다
  onArrivedEnd: (arrival: TabArrival) => void;
  onSelect: (tab: FeedTab) => void;
}

export default function FeedTabs({ tab, counts, arrived, onArrivedEnd, onSelect }: FeedTabsProps) {
  return (
    <>
      <h2 className="sr-only">공고 목록</h2>
      <div role="group" aria-label="공고 목록" className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        {feedTabs.map((feedTab) => {
          const arriving = arrived?.tab === feedTab.value ? arrived : null;
          return (
            <button
              key={feedTab.value}
              type="button"
              onClick={() => onSelect(feedTab.value)}
              aria-pressed={tab === feedTab.value}
              className={`text-[20px] font-semibold transition-colors ${
                tab === feedTab.value ? "text-[#181a20]" : "text-[#a0a4ab] hover:text-[#667085]"
              }`}
            >
              <span
                key={arriving?.id ?? 0}
                className={arriving ? "tab-arrive" : undefined}
                onAnimationEnd={arriving ? () => onArrivedEnd(arriving) : undefined}
              >
                {feedTab.label}
                {feedTab.value !== "recommended" && counts[feedTab.value] > 0 && (
                  <span className="ml-1 text-[14px]">{counts[feedTab.value]}</span>
                )}
              </span>
            </button>
          );
        })}
      </div>
    </>
  );
}
