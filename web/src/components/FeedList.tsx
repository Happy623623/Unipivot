import { useRef, type ReactNode } from "react";
import Pager from "@/components/Pager";
import type { Paged } from "@/lib/paginate";
import type { OpportunityItem } from "@/types/api";

interface FeedListProps {
  listKey: string; // 목록이 바뀌거나 쪽을 넘기면 목록이 다시 나타나며 움직인다
  main: Paged<OpportunityItem>; // 지금 쪽의 공고(지원 어려움 빼고)
  group: Paged<OpportunityItem>; // 지원 어려움 묶음의 지금 쪽
  groupTotal: number;
  showGroup: boolean;
  onToggleGroup: () => void;
  onPage: (page: number) => void;
  onGroupPage: (page: number) => void;
  card: (item: OpportunityItem) => ReactNode;
}

// 쪽을 넘겼는데 목록 머리가 화면 위로 지나가 있으면 머리로 올린다
function showTop(element: HTMLElement | null) {
  if (element && element.getBoundingClientRect().top < 0) element.scrollIntoView({ block: "start" });
}

// 홈 공고 목록(F-40). 5개씩 쪽으로 나누고, 지원 어려움 묶음은 쪽마다 맨 아래에 둔다(기본은 접힘, 펼치면 그 안도 5개씩)
export default function FeedList({ listKey, main, group, groupTotal, showGroup, onToggleGroup, onPage, onGroupPage, card }: FeedListProps) {
  const mainRef = useRef<HTMLDivElement>(null);
  const groupRef = useRef<HTMLDivElement>(null);
  return (
    <>
      <div ref={mainRef} key={`${listKey}-${main.page}`} className="opportunity-list mt-7 flex scroll-mt-6 flex-col gap-7">
        {main.items.map(card)}
      </div>
      <Pager
        label="공고 목록 쪽"
        page={main.page}
        pageCount={main.pageCount}
        onChange={(page) => {
          onPage(page);
          showTop(mainRef.current);
        }}
      />
      {groupTotal > 0 && (
        <div ref={groupRef} className="mt-7 scroll-mt-6">
          <button
            type="button"
            onClick={onToggleGroup}
            aria-expanded={showGroup}
            className="flex w-full items-center justify-between rounded-[14px] border border-[#e5e7eb] bg-white p-4 text-[14px] font-semibold"
          >
            지원 어려움 {groupTotal}개
            <span className="text-[#667085]">{showGroup ? "⌃" : "⌄"}</span>
          </button>
          {showGroup && (
            <>
              <div className="mt-3 flex flex-col gap-3">{group.items.map(card)}</div>
              <Pager
                label="지원 어려움 쪽"
                page={group.page}
                pageCount={group.pageCount}
                onChange={(page) => {
                  onGroupPage(page);
                  showTop(groupRef.current);
                }}
              />
            </>
          )}
        </div>
      )}
    </>
  );
}
