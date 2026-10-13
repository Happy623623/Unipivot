import type { FeedCounts } from "@/types/api";

export type SummaryFilter = "eligible" | "undetermined" | "deadline_soon";

interface FeedSummaryProps {
  counts: FeedCounts;
  selected: SummaryFilter | null;
  onToggle: (filter: SummaryFilter) => void;
}

// 홈 요약 카드 3개(F-40). 숫자는 카테고리와 상관없는 전체 기준이고 숨긴 공고(F-45)는 세지 않는다.
// 누르면 추천 공고를 그 상태로 거른다
export default function FeedSummary({ counts, selected, onToggle }: FeedSummaryProps) {
  const cards: { filter: SummaryFilter; title: string; value: number; tone: string; note: string }[] = [
    { filter: "eligible", title: "지원 가능", value: counts.eligible, tone: "text-[#15803d]", note: `새 공고 ${counts.new_eligible}개` },
    {
      filter: "undetermined",
      title: "확인 필요",
      value: counts.undetermined,
      tone: "text-[#b7791f]",
      note: `정보 입력 ${counts.missing_info} · 원문 확인 ${counts.needs_review}`,
    },
    { filter: "deadline_soon", title: "마감 임박", value: counts.deadline_soon, tone: "text-[#c53030]", note: "3일 이내" },
  ];
  return (
    <section className="grid max-w-[786px] grid-cols-3 gap-4 max-[760px]:grid-cols-1">
      {cards.map((card) => (
        <button
          key={card.filter}
          type="button"
          onClick={() => onToggle(card.filter)}
          aria-pressed={selected === card.filter}
          className={`h-28 rounded-2xl border bg-white p-5 text-left ${
            selected === card.filter ? "border-[#4f6ef7]" : "border-[#e5e7eb]"
          }`}
        >
          <p className="text-[13px] font-medium text-[#667085]">{card.title}</p>
          <p className={`text-[28px] font-bold leading-9 ${card.tone}`}>{card.value}</p>
          <p className="text-[12px] text-[#667085]">{card.note}</p>
        </button>
      ))}
    </section>
  );
}
