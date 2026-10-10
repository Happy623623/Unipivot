import { useState } from "react";
import { getFeed, getMe, MOCK_TODAY, type FeedParams } from "@/api/client";
import Badge from "@/components/Badge";
import Header from "@/components/Header";
import Skeleton from "@/components/Skeleton";
import StatusBadge from "@/components/StatusBadge";
import { formatDday, getCategoryLabel, getSourceLabel } from "@/lib/format";
import useAsyncData from "@/lib/useAsyncData";
import type { Category, DisplayStatus, OpportunityItem } from "@/types/api";
import type { Route } from "@/types/route";

interface HomeProps {
  navigate: (route: Route) => void;
}

type SummaryFilter = "eligible" | "undetermined" | "deadline_soon";

const categoryFilters: { label: string; value: Category | "all" }[] = [
  { label: "전체", value: "all" },
  { label: "장학금", value: "scholarship" },
  { label: "교내 프로그램", value: "school_program" },
  { label: "청년정책", value: "youth_policy" },
  { label: "공모전", value: "contest" },
  { label: "대외활동", value: "activity" },
  { label: "기타", value: "etc" },
];

const statusMarks: Record<DisplayStatus, string> = {
  eligible: "✓",
  missing_info: "!",
  needs_review: "□",
  ineligible: "×",
};

function HomeSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[360px]" />
      <div className="grid max-w-[786px] grid-cols-3 gap-4">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-44 w-full rounded-2xl" />
      <Skeleton className="h-44 w-full rounded-2xl" />
    </>
  );
}

function OpportunityCard({ item, navigate }: { item: OpportunityItem; navigate: (route: Route) => void }) {
  const displayStatus = item.eligibility.display_status;
  const reasonTone =
    displayStatus === "eligible"
      ? "bg-[#ecfdf3] text-[#15803d]"
      : displayStatus === "missing_info"
        ? "bg-[#fff8e1] text-[#b7791f]"
        : displayStatus === "needs_review"
          ? "bg-[#f2f4f7] text-[#475467]"
          : "bg-[#fef2f2] text-[#c53030]";
  const deadlineSoon = item.d_day !== null && item.d_day >= 0 && item.d_day <= 3;
  const context =
    item.source_type === "poster" && item.uploader_masked
      ? `${item.uploader_masked}님 공유`
      : item.source_type === "lms_announcement" && item.course_name
        ? `${item.course_name} 수강생 대상`
        : null;
  const sourceAction = item.source_type === "poster" ? "포스터 보기" : "원문 보기";

  return (
    <button
      type="button"
      onClick={() => navigate({ name: "opportunity", id: item.id })}
      className="opportunity-card group w-full rounded-2xl border border-[#e5e7eb] bg-white p-[22px] text-left transition-all duration-300 hover:-translate-y-1 hover:border-[#cfd7ff] hover:shadow-[0_14px_36px_rgba(79,110,247,0.11)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f6ef7]"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge>{getCategoryLabel(item.category)}</Badge>
          <span className="text-[12px] font-medium text-[#667085]">{item.organizer}</span>
          {context && <span className="text-[12px] text-[#667085]">· {context}</span>}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <StatusBadge displayStatus={displayStatus} />
          {item.eligibility.display_status === "eligible" && item.needs_review && (
            <Badge tone="gray">원문 확인 필요</Badge>
          )}
          <span className={`text-[12px] font-semibold ${deadlineSoon ? "text-[#c53030]" : "text-[#667085]"}`}>
            {deadlineSoon && "마감 임박 "}
            {formatDday(item.deadline_at, MOCK_TODAY)}
          </span>
        </div>
      </div>
      <h3 className="mt-3 flex items-center gap-2 text-[18px] font-semibold leading-[1.45]">
        {item.is_new && <span className="size-2 shrink-0 rounded-full bg-[#4f6ef7]" />}
        {item.title}
      </h3>
      <p className="mt-2 text-[13px] text-[#667085]">{item.easy_summary}</p>
      <div className={`mt-3 inline-flex items-center gap-2 rounded-[10px] px-3 py-[9px] text-[13px] font-medium ${reasonTone}`}>
        <b>{statusMarks[displayStatus]}</b>
        <span className="truncate">{item.eligibility.summary}</span>
      </div>
      <div className="mt-3 flex items-center justify-between text-[12px] text-[#667085]">
        <span>{getSourceLabel(item.source_type)} · {sourceAction}</span>
        <span className="translate-x-1 text-[18px] text-[#4f6ef7] opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100">→</span>
      </div>
    </button>
  );
}

export default function Home({ navigate }: HomeProps) {
  const [category, setCategory] = useState<Category | "all">("all");
  const [summaryFilter, setSummaryFilter] = useState<SummaryFilter | null>(null);
  const [sort, setSort] = useState<FeedParams["sort"]>("deadline");
  const [showIneligible, setShowIneligible] = useState(false);
  const request = useAsyncData(
    () => Promise.all([getMe(), getFeed({ sort }), getFeed({ category, sort })]),
    [category, sort],
  );

  if (request.loading) return <HomeSkeleton />;
  if (request.error || !request.data) {
    return <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">{request.error ?? "홈 데이터를 불러오지 못했어요."}</p>;
  }

  const [me, fullFeed, filteredFeed] = request.data;
  const summaryFilteredItems = filteredFeed.items.filter((item) => {
    if (summaryFilter === "eligible") return item.eligibility.display_status === "eligible";
    if (summaryFilter === "undetermined") return item.eligibility.status === "undetermined";
    if (summaryFilter === "deadline_soon") {
      return item.eligibility.status !== "ineligible" && item.d_day !== null && item.d_day >= 0 && item.d_day <= 3;
    }
    return true;
  });
  const visibleItems = summaryFilteredItems.filter((item) => item.eligibility.display_status !== "ineligible");
  const ineligibleItems = summaryFilteredItems.filter((item) => item.eligibility.display_status === "ineligible");
  const counts = fullFeed.counts;
  const hasFilteredResults = visibleItems.length + ineligibleItems.length > 0;
  const isEmptyFeed = fullFeed.items.length === 0;

  const toggleSummary = (filter: SummaryFilter) => {
    setSummaryFilter((current) => (current === filter ? null : filter));
    setShowIneligible(false);
  };

  const resetFilters = () => {
    setCategory("all");
    setSummaryFilter(null);
    setSort("deadline");
    setShowIneligible(false);
  };

  return (
    <>
      <Header title={`안녕하세요, ${me.display_name}님`} subtitle="나에게 맞는 기회와 이번 주 할 일을 한눈에 확인하세요." />
      <section className="grid max-w-[786px] grid-cols-3 gap-4 max-[760px]:grid-cols-1">
        <button
          type="button"
          onClick={() => toggleSummary("eligible")}
          aria-pressed={summaryFilter === "eligible"}
          className={`h-28 rounded-2xl border bg-white p-5 text-left ${
            summaryFilter === "eligible" ? "border-[#4f6ef7]" : "border-[#e5e7eb]"
          }`}
        >
          <p className="text-[13px] font-medium text-[#667085]">지원 가능</p>
          <p className="text-[28px] font-bold leading-9 text-[#15803d]">{counts.eligible}</p>
          <p className="text-[12px] text-[#667085]">새 공고 {counts.new_eligible}개</p>
        </button>
        <button
          type="button"
          onClick={() => toggleSummary("undetermined")}
          aria-pressed={summaryFilter === "undetermined"}
          className={`h-28 rounded-2xl border bg-white p-5 text-left ${
            summaryFilter === "undetermined" ? "border-[#4f6ef7]" : "border-[#e5e7eb]"
          }`}
        >
          <p className="text-[13px] font-medium text-[#667085]">확인 필요</p>
          <p className="text-[28px] font-bold leading-9 text-[#b7791f]">{counts.undetermined}</p>
          <p className="text-[12px] text-[#667085]">정보 입력 {counts.missing_info} · 원문 확인 {counts.needs_review}</p>
        </button>
        <button
          type="button"
          onClick={() => toggleSummary("deadline_soon")}
          aria-pressed={summaryFilter === "deadline_soon"}
          className={`h-28 rounded-2xl border bg-white p-5 text-left ${
            summaryFilter === "deadline_soon" ? "border-[#4f6ef7]" : "border-[#e5e7eb]"
          }`}
        >
          <p className="text-[13px] font-medium text-[#667085]">마감 임박</p>
          <p className="text-[28px] font-bold leading-9 text-[#c53030]">{counts.deadline_soon}</p>
          <p className="text-[12px] text-[#667085]">3일 이내</p>
        </button>
      </section>
      <section>
        <div className="flex items-center justify-between">
          <h2 className="text-[20px] font-semibold">추천 공고</h2>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as NonNullable<FeedParams["sort"]>)}
            className="bg-transparent text-[13px] font-medium text-[#667085] outline-none"
          >
            <option value="deadline">마감 임박순</option>
            <option value="recent">최신순</option>
          </select>
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          {categoryFilters.map((filter) => (
            <button
              key={filter.value}
              type="button"
              onClick={() => setCategory(filter.value)}
              className={`filter-chip rounded-full transition-all duration-300 ${
                category === filter.value
                  ? "-translate-y-0.5 scale-105 shadow-[0_6px_16px_rgba(79,110,247,0.18)]"
                  : "opacity-55 hover:-translate-y-0.5 hover:scale-105 hover:opacity-100"
              }`}
              aria-pressed={category === filter.value}
            >
              <Badge>{filter.label}</Badge>
            </button>
          ))}
        </div>
        {isEmptyFeed ? (
          <div className="mt-7 rounded-2xl border border-dashed border-[#e5e7eb] bg-white p-10 text-center">
            <p className="text-[16px] font-semibold">포스터를 올리면 공고로 등록하고 자격을 판정해요</p>
            <button type="button" onClick={() => navigate({ name: "upload" })} className="mt-3 text-[13px] font-semibold text-[#4f6ef7]">
              포스터 등록
            </button>
          </div>
        ) : !hasFilteredResults ? (
          <div className="mt-7 rounded-2xl border border-dashed border-[#e5e7eb] bg-white p-10 text-center">
            <p className="text-[16px] font-semibold">조건에 맞는 공고가 없어요</p>
            <button type="button" onClick={resetFilters} className="mt-3 text-[13px] font-semibold text-[#4f6ef7]">
              필터 초기화
            </button>
          </div>
        ) : (
          <>
            <div key={`${category}-${summaryFilter}-${sort}`} className="opportunity-list mt-7 flex flex-col gap-7">
              {visibleItems.map((item) => <OpportunityCard key={item.id} item={item} navigate={navigate} />)}
            </div>
            {ineligibleItems.length > 0 && (
              <div className="mt-7">
                <button
                  type="button"
                  onClick={() => setShowIneligible((value) => !value)}
                  className="flex w-full items-center justify-between rounded-[14px] border border-[#e5e7eb] bg-white p-4 text-[14px] font-semibold"
                >
                  지원 어려움 {ineligibleItems.length}개
                  <span className="text-[#667085]">{showIneligible ? "⌃" : "⌄"}</span>
                </button>
                {showIneligible && (
                  <div className="mt-3 flex flex-col gap-3">
                    {ineligibleItems.map((item) => <OpportunityCard key={item.id} item={item} navigate={navigate} />)}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </section>
    </>
  );
}
