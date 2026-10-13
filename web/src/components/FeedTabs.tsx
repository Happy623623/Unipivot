// 홈 공고 목록 탭(F-45). 추천 공고는 숨긴 공고를 뺀 전부, 관심·숨김은 그 표시를 한 공고만이다.
// 관심·숨김 숫자는 지금 고른 카테고리 안에서 센다(0이면 숫자를 쓰지 않는다)
export type FeedTab = "recommended" | "interested" | "not_interested";

const feedTabs: { label: string; value: FeedTab }[] = [
  { label: "추천 공고", value: "recommended" },
  { label: "관심", value: "interested" },
  { label: "숨김", value: "not_interested" },
];

interface FeedTabsProps {
  tab: FeedTab;
  counts: Record<Exclude<FeedTab, "recommended">, number>;
  onSelect: (tab: FeedTab) => void;
}

export default function FeedTabs({ tab, counts, onSelect }: FeedTabsProps) {
  return (
    <>
      <h2 className="sr-only">공고 목록</h2>
      <div role="group" aria-label="공고 목록" className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        {feedTabs.map((feedTab) => (
          <button
            key={feedTab.value}
            type="button"
            onClick={() => onSelect(feedTab.value)}
            aria-pressed={tab === feedTab.value}
            className={`text-[20px] font-semibold transition-colors ${
              tab === feedTab.value ? "text-[#181a20]" : "text-[#a0a4ab] hover:text-[#667085]"
            }`}
          >
            {feedTab.label}
            {feedTab.value !== "recommended" && counts[feedTab.value] > 0 && (
              <span className="ml-1 text-[14px]">{counts[feedTab.value]}</span>
            )}
          </button>
        ))}
      </div>
    </>
  );
}
