import Badge from "@/components/Badge";
import type { Category } from "@/types/api";

export type CategoryFilter = Category | "all";

const categoryFilters: { label: string; value: CategoryFilter }[] = [
  { label: "전체", value: "all" },
  { label: "장학금", value: "scholarship" },
  { label: "교내 프로그램", value: "school_program" },
  { label: "청년정책", value: "youth_policy" },
  { label: "공모전", value: "contest" },
  { label: "대외활동", value: "activity" },
  { label: "기타", value: "etc" },
];

// 홈 카테고리 칩(F-40). "기타"는 연구·시험·기타를 함께 고른다(client.ts feedCategories)
export default function CategoryChips({ value, onChange }: { value: CategoryFilter; onChange: (next: CategoryFilter) => void }) {
  return (
    <div className="mt-5 flex flex-wrap gap-2">
      {categoryFilters.map((filter) => (
        <button
          key={filter.value}
          type="button"
          onClick={() => onChange(filter.value)}
          className={`filter-chip rounded-full transition-all duration-300 ${
            value === filter.value
              ? "-translate-y-0.5 scale-105 shadow-[0_6px_16px_rgba(79,110,247,0.18)]"
              : "opacity-55 hover:-translate-y-0.5 hover:scale-105 hover:opacity-100"
          }`}
          aria-pressed={value === filter.value}
        >
          <Badge>{filter.label}</Badge>
        </button>
      ))}
    </div>
  );
}
