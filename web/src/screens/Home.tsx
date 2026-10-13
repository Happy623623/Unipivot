import { useEffect, useRef, useState } from "react";
import { errorMessage, getFeed, getMe, POSTER_READY, setOpportunityMark, type FeedParams } from "@/api/client";
import Badge from "@/components/Badge";
import FeedSummary, { type SummaryFilter } from "@/components/FeedSummary";
import FeedTabs, { type FeedTab } from "@/components/FeedTabs";
import Header from "@/components/Header";
import OpportunityCard from "@/components/OpportunityCard";
import { markError, markToast } from "@/components/OpportunityMarkButtons";
import Skeleton from "@/components/Skeleton";
import Toast from "@/components/Toast";
import { adjustCounts } from "@/lib/feedCounts";
import useAsyncData from "@/lib/useAsyncData";
import useToast from "@/lib/useToast";
import type { Category, OpportunityItem, OpportunityMark } from "@/types/api";
import type { Route } from "@/types/route";

interface HomeProps {
  navigate: (route: Route) => void;
}

const categoryFilters: { label: string; value: Category | "all" }[] = [
  { label: "전체", value: "all" },
  { label: "장학금", value: "scholarship" },
  { label: "교내 프로그램", value: "school_program" },
  { label: "청년정책", value: "youth_policy" },
  { label: "공모전", value: "contest" },
  { label: "대외활동", value: "activity" },
  { label: "기타", value: "etc" },
];

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

interface EmptyState {
  title: string;
  action: string;
  onAction: () => void;
}

function EmptyBox({ title, action, onAction }: EmptyState) {
  return (
    <div className="mt-7 rounded-2xl border border-dashed border-[#e5e7eb] bg-white p-10 text-center">
      <p className="text-[16px] font-semibold">{title}</p>
      <button type="button" onClick={onAction} className="mt-3 text-[13px] font-semibold text-[#4f6ef7]">
        {action}
      </button>
    </div>
  );
}

export default function Home({ navigate }: HomeProps) {
  const [category, setCategory] = useState<Category | "all">("all");
  const [summaryFilter, setSummaryFilter] = useState<SummaryFilter | null>(null);
  const [sort, setSort] = useState<FeedParams["sort"]>("deadline");
  const [tab, setTab] = useState<FeedTab>("recommended");
  const [showIneligible, setShowIneligible] = useState(false);
  const [reload, setReload] = useState(0);
  // 이 화면에서 바꾼 표시(F-45). 목록을 다시 받아도 남기고, 요약 숫자는 서버 값에서 그만큼 고쳐 보여 준다
  const [marks, setMarks] = useState<Record<string, OpportunityMark | null>>({});
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [toast, showToast] = useToast();
  const listRef = useRef<HTMLElement>(null);
  const focusAt = useRef<number | null>(null); // 표시를 바꿔 카드가 탭에서 빠지면 초점을 둘 자리(그 카드가 있던 순서)
  // 판정 결과를 숨긴 공고까지 모두 받아 화면에서 묶는다. 요약 카드 숫자(counts)는 카테고리와 상관없는 전체 기준이다
  const request = useAsyncData(
    () =>
      Promise.all([getMe(), getFeed({ category, sort })]).catch((error: unknown) => {
        throw new Error(errorMessage(error, "공고를 불러오지 못했어요. 잠시 후 새로 고쳐 주세요."));
      }),
    [category, sort, reload],
  );
  const latestData = useRef(request.data); // 표시를 저장하는 사이 목록을 다시 받기 시작했는지 본다
  useEffect(() => {
    latestData.current = request.data;
  });

  // 빠진 카드 자리의 다음 카드(맨 끝이면 앞 카드, 카드가 없으면 지금 탭 버튼)에 초점을 둔다.
  // 그새 다른 곳을 눌렀으면 그대로 둔다(빠진 카드와 함께 초점을 잃었을 때만 옮긴다)
  useEffect(() => {
    const index = focusAt.current;
    focusAt.current = null;
    const list = listRef.current;
    if (index === null || !list) return;
    const active = list.ownerDocument.activeElement;
    if (active && active !== list.ownerDocument.body) return;
    const cards = list.querySelectorAll<HTMLElement>("[data-card]");
    (cards[Math.min(index, cards.length - 1)] ?? list.querySelector<HTMLElement>('[role="group"] [aria-pressed="true"]'))?.focus();
  });

  if (request.loading) return <HomeSkeleton />;
  if (request.error || !request.data) {
    return <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">{request.error ?? "홈 데이터를 불러오지 못했어요."}</p>;
  }

  const [me, feed] = request.data;
  const shownCounts = adjustCounts(feed.counts, feed.items, marks);
  const items = feed.items.map((item) => (item.id in marks ? { ...item, my_mark: marks[item.id] } : item));
  const tabItems = items.filter((item) =>
    tab === "recommended" ? item.my_mark !== "not_interested" : item.my_mark === tab,
  );
  const tabCounts = {
    interested: items.filter((item) => item.my_mark === "interested").length,
    not_interested: items.filter((item) => item.my_mark === "not_interested").length,
  };
  const summaryFilteredItems = tabItems.filter((item) => {
    if (summaryFilter === "eligible") return item.eligibility.display_status === "eligible";
    if (summaryFilter === "undetermined") return item.eligibility.status === "undetermined";
    if (summaryFilter === "deadline_soon") {
      return item.eligibility.status !== "ineligible" && item.d_day !== null && item.d_day >= 0 && item.d_day <= 3;
    }
    return true;
  });
  // 지원 어려움 공고는 탭마다 목록 맨 아래 "지원 어려움 N개" 묶음으로 모은다(기본은 접힘)
  const visibleItems = summaryFilteredItems.filter((item) => item.eligibility.display_status !== "ineligible");
  const ineligibleItems = summaryFilteredItems.filter((item) => item.eligibility.display_status === "ineligible");
  // 볼 공고가 하나도 없음(숨긴 공고도 없음). 숨긴 공고 수는 고른 카테고리 안에서만 알아서 전체 카테고리에서만 본다
  const isEmptyFeed =
    category === "all" &&
    shownCounts.eligible + shownCounts.undetermined + shownCounts.ineligible === 0 &&
    tabCounts.not_interested === 0;

  const selectTab = (next: FeedTab) => {
    setTab(next);
    setSummaryFilter(null);
    setShowIneligible(false);
  };

  // 요약 카드 숫자는 추천 공고 기준이라 추천 공고 탭에서 거른다
  const toggleSummary = (filter: SummaryFilter) => {
    setTab("recommended");
    setSummaryFilter((current) => (current === filter ? null : filter));
    setShowIneligible(false);
  };

  const resetFilters = () => {
    setCategory("all");
    selectTab("recommended");
    setSort("deadline");
  };

  // 빈 목록이면 다음 행동 하나를 버튼과 함께 안내한다. 관심·숨김은 지금 고른 카테고리 안에서 본다
  const emptyState = (): EmptyState | null => {
    const all = category === "all";
    if (isEmptyFeed) {
      // 실제 모드는 포스터 등록(W6) 전이라 다시 불러오기를 안내한다
      return POSTER_READY
        ? { title: "포스터를 올리면 공고로 등록하고 자격을 판정해요", action: "포스터 등록", onAction: () => navigate({ name: "upload" }) }
        : { title: "아직 볼 수 있는 공고가 없어요. 새 공고가 올라오면 여기에 보여요", action: "다시 불러오기", onAction: () => setReload((value) => value + 1) };
    }
    if (tabItems.length === 0 && tab === "recommended" && tabCounts.not_interested > 0) {
      const title = all ? "공고를 모두 숨겼어요" : "이 카테고리의 공고를 모두 숨겼어요";
      return { title, action: "숨김 탭 보기", onAction: () => selectTab("not_interested") };
    }
    if (tabItems.length === 0 && tab !== "recommended") {
      const title =
        tab === "interested"
          ? all ? "관심 공고가 없어요. 카드의 ☆ 관심을 누르면 여기에 모여요" : "이 카테고리에는 관심 공고가 없어요"
          : all ? "숨긴 공고가 없어요" : "이 카테고리에는 숨긴 공고가 없어요";
      return all
        ? { title, action: "추천 공고 보기", onAction: () => selectTab("recommended") }
        : { title, action: "전체 카테고리 보기", onAction: () => setCategory("all") };
    }
    if (visibleItems.length + ineligibleItems.length === 0) {
      return { title: "조건에 맞는 공고가 없어요", action: "필터 초기화", onAction: resetFilters };
    }
    return null;
  };
  const empty = emptyState();

  const changeMark = async (item: OpportunityItem, next: OpportunityMark | null) => {
    // 바뀐 뒤 이 탭에서 빠지는 카드면 그 자리로 초점을 옮긴다(화면의 카드 순서와 같다)
    const leaves = tab === "recommended" ? next === "not_interested" : next !== tab;
    const shown = [...visibleItems, ...(showIneligible ? ineligibleItems : [])];
    const index = shown.findIndex((entry) => entry.id === item.id);
    const before = request.data;
    setPending((current) => new Set(current).add(item.id));
    try {
      await setOpportunityMark(item.id, next);
      if (leaves) focusAt.current = index;
      setMarks((current) => ({ ...current, [item.id]: next }));
      showToast(markToast(item.my_mark, next));
      // 저장하는 사이 목록을 다시 받기 시작했으면 저장 전 값을 읽었을 수 있다. 숫자가 어긋나지 않게 한 번 더 받는다
      if (latestData.current !== before) setReload((value) => value + 1);
    } catch (error) {
      showToast(markError(error));
    } finally {
      setPending((current) => {
        const rest = new Set(current);
        rest.delete(item.id);
        return rest;
      });
    }
  };

  const card = (item: OpportunityItem) => (
    <OpportunityCard key={item.id} item={item} pending={pending.has(item.id)} navigate={navigate} onMark={changeMark} />
  );

  return (
    <>
      <Header title={`안녕하세요, ${me.display_name}님`} subtitle="나에게 맞는 기회와 이번 주 할 일을 한눈에 확인하세요." />
      <FeedSummary counts={shownCounts} selected={summaryFilter} onToggle={toggleSummary} />
      <section ref={listRef}>
        <div className="flex items-center justify-between gap-3">
          <FeedTabs tab={tab} counts={tabCounts} onSelect={selectTab} />
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
        {empty ? (
          <EmptyBox {...empty} />
        ) : (
          <>
            <div key={`${category}-${summaryFilter}-${sort}-${tab}`} className="opportunity-list mt-7 flex flex-col gap-7">
              {visibleItems.map(card)}
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
                {showIneligible && <div className="mt-3 flex flex-col gap-3">{ineligibleItems.map(card)}</div>}
              </div>
            )}
          </>
        )}
      </section>
      <Toast toast={toast} />
    </>
  );
}
