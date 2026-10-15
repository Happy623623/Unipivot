import { useEffect, useRef, useState, type ReactNode } from "react";
import { errorMessage, getFeed, getMe, POSTER_EXTRACT_READY, setOpportunityMark, type FeedParams } from "@/api/client";
import CategoryChips, { type CategoryFilter } from "@/components/CategoryChips";
import FeedList from "@/components/FeedList";
import FeedSummary, { type SummaryFilter } from "@/components/FeedSummary";
import FeedTabs, { arrivalTab, showTabLabel, type FeedTab, type TabArrival } from "@/components/FeedTabs";
import Header from "@/components/Header";
import { EmptyBox, HomeSkeleton, type EmptyState } from "@/components/HomeStates";
import OpportunityCard from "@/components/OpportunityCard";
import { markError, markToast } from "@/components/OpportunityMarkButtons";
import Toast from "@/components/Toast";
import { adjustCounts } from "@/lib/feedCounts";
import { feedListKey, feedView } from "@/lib/feedView";
import { PAGE_SIZE, pageOf, paginate, type PageAt } from "@/lib/paginate";
import useAsyncData from "@/lib/useAsyncData";
import useCardFocus from "@/lib/useCardFocus";
import useToast from "@/lib/useToast";
import type { OpportunityItem, OpportunityMark } from "@/types/api";
import type { Route } from "@/types/route";

interface HomeProps {
  navigate: (route: Route) => void;
}

export default function Home({ navigate }: HomeProps) {
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [summaryFilter, setSummaryFilter] = useState<SummaryFilter | null>(null);
  const [sort, setSort] = useState<FeedParams["sort"]>("deadline");
  const [tab, setTab] = useState<FeedTab>("recommended");
  const [showIneligible, setShowIneligible] = useState(false);
  const [pageAt, setPageAt] = useState<PageAt>({ key: "", page: 1 }); // 목록 쪽(5개씩)
  const [groupPageAt, setGroupPageAt] = useState<PageAt>({ key: "", page: 1 }); // 지원 어려움 묶음 쪽
  const [reload, setReload] = useState(0);
  // 이 화면에서 바꾼 표시(F-45). 목록을 다시 받아도 남기고, 요약 숫자는 서버 값에서 그만큼 고쳐 보여 준다
  const [marks, setMarks] = useState<Record<string, OpportunityMark | null>>({});
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [arrived, setArrived] = useState<TabArrival | null>(null); // 방금 공고가 들어간 탭(잠깐 강조)
  const [find, setFind] = useState<string | null>(null); // 안내의 "…보기"로 찾아갈 공고(그 쪽을 연다)
  const [found, setFound] = useState<{ id: string; n: number } | null>(null); // 찾아간 공고 카드(잠깐 강조)
  const foundCount = useRef(0); // 강조마다 번호를 새로 줘서 앞 강조의 타이머가 새 강조를 일찍 끄지 않게 한다
  const [toast, showToast, hideToast, holdToast] = useToast();
  const listRef = useRef<HTMLElement>(null);
  const cardFocus = useCardFocus(listRef);
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

  // 안내 자리는 목록을 다시 받는 동안에도 둔다. 사라지면 붙잡은 안내가 풀리지 않고 화면 읽기 프로그램이 놓친다
  const withToast = (body: ReactNode) => (
    <>
      {body}
      <Toast toast={toast} onHold={holdToast} />
    </>
  );

  if (request.loading) {
    if (arrived) setArrived(null); // 탭이 잠깐 사라져 강조가 끝나지 않으니 지운다(다시 나타날 때 또 움직이지 않게)
    return withToast(<HomeSkeleton />);
  }
  if (request.error || !request.data) {
    return withToast(
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">{request.error ?? "홈 데이터를 불러오지 못했어요."}</p>,
    );
  }

  const [me, feed] = request.data;
  const shownCounts = adjustCounts(feed.counts, feed.items, marks);
  const items = feed.items.map((item) => (item.id in marks ? { ...item, my_mark: marks[item.id] } : item));
  const { tabItems, visible: visibleItems, ineligible: ineligibleItems } = feedView(items, tab, summaryFilter);
  const tabCounts = {
    interested: items.filter((item) => item.my_mark === "interested").length,
    not_interested: items.filter((item) => item.my_mark === "not_interested").length,
  };
  const listKey = feedListKey(category, summaryFilter, sort, tab);
  const main = paginate(visibleItems, pageAt, listKey);
  const group = paginate(ineligibleItems, groupPageAt, listKey);
  if (find) {
    // 안내의 "…보기"로 온 공고가 있는 쪽을 연다. 지원 어려움 공고면 묶음을 펼치고 그 안의 쪽을 연다
    const inMain = visibleItems.findIndex((entry) => entry.id === find);
    const inGroup = ineligibleItems.findIndex((entry) => entry.id === find);
    setFind(null);
    setPageAt({ key: listKey, page: inMain < 0 ? 1 : pageOf(inMain) });
    setGroupPageAt({ key: listKey, page: inGroup < 0 ? 1 : pageOf(inGroup) });
    setShowIneligible(inGroup >= 0);
  } else {
    // 목록(탭·카테고리·정렬·요약 카드)이 바뀌면 1쪽부터 보고, 공고가 빠져 쪽 수가 줄면 마지막 쪽을 보인다.
    // 저장하는 동안은 원래 쪽을 기억해 두어, 저장하지 못해 공고가 돌아오면 그 쪽을 다시 보인다
    const hold = pending.size > 0;
    if (pageAt.key !== listKey || (!hold && pageAt.page !== main.page)) setPageAt({ key: listKey, page: main.page });
    if (groupPageAt.key !== listKey || (!hold && groupPageAt.page !== group.page)) setGroupPageAt({ key: listKey, page: group.page });
  }
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

  // 안내의 "…보기": 그 탭에서 옮긴 공고가 있는 쪽을 열고, 그 카드에 초점을 두고 잠깐 강조한다. 안내는 닫는다.
  // 안내 버튼은 누르기 전 화면에서 만든 것이라 목록은 다음 그리기에서(find) 찾는다
  const openTab = (next: FeedTab, id: string) => {
    selectTab(next);
    setFind(id);
    const n = (foundCount.current += 1);
    setFound({ id, n });
    setTimeout(() => setFound((current) => (current?.n === n ? null : current)), 1600);
    cardFocus.current = { kind: "reveal", id };
    hideToast();
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
      // 포스터에서 공고를 뽑는 기능(W6 2차) 전에는 등록을 권할 수 없어 다시 불러오기를 안내한다
      return POSTER_EXTRACT_READY
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

  // 서버 답을 기다리지 않고 바로 옮긴다. 들어간 탭을 강조하고 안내에 그 탭 보기 버튼을 단다. 저장하지 못하면 되돌린다
  const changeMark = async (item: OpportunityItem, next: OpportunityMark | null) => {
    const before = item.my_mark;
    const changed = item.id in marks; // 이 화면에서 바꾼 적이 있는 공고(되돌릴 때 그 값으로 돌린다)
    const kept = marks[item.id];
    // 바뀐 뒤 이 탭에서 빠지는 카드면 그 자리로 초점을 옮긴다(보이는 카드 순서는 지금 쪽 목록 뒤에 펼친 묶음).
    // 쪽에 혼자 있던 카드면 앞 쪽으로 넘어가니 앞 쪽의 마지막 카드다
    const leaves = tab === "recommended" ? next === "not_interested" : next !== tab;
    const inGroup = !main.items.some((entry) => entry.id === item.id);
    const own = inGroup ? group : main;
    const index = (inGroup ? main.items.length : 0) + own.items.findIndex((entry) => entry.id === item.id);
    const alone = own.items.length === 1 && own.page > 1;
    const arrival = arrivalTab(before, next);
    const dataAtClick = request.data;
    if (leaves) cardFocus.current = { kind: "leave", index: alone ? index + PAGE_SIZE - 1 : index };
    setMarks((current) => ({ ...current, [item.id]: next }));
    if (arrival) setArrived((current) => ({ tab: arrival, id: (current?.id ?? 0) + 1 }));
    const goTo = arrival && arrival !== tab ? arrival : null;
    showToast(markToast(before, next, "home"), goTo ? { label: showTabLabel(goTo), onAction: () => openTab(goTo, item.id) } : undefined);
    setPending((current) => new Set(current).add(item.id));
    try {
      await setOpportunityMark(item.id, next);
      // 저장하는 사이 목록을 다시 받기 시작했으면 저장 전 값을 읽었을 수 있다. 숫자가 어긋나지 않게 한 번 더 받는다
      if (latestData.current !== dataAtClick) setReload((value) => value + 1);
    } catch (error) {
      // 되돌린다. 이 화면에서 바꾼 적이 없던 공고면 서버 값을 다시 따른다. 초점을 잃었으면(카드가 빠졌거나 안내 버튼이
      // 바뀌었다) 돌아온 카드에, 그 카드가 이 탭에 없으면 지금 탭 버튼에 둔다
      setMarks((current) => {
        const rest = { ...current };
        if (changed) rest[item.id] = kept;
        else delete rest[item.id];
        return rest;
      });
      cardFocus.current = { kind: "back", id: item.id };
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
    <OpportunityCard
      key={item.id}
      item={item}
      pending={pending.has(item.id)}
      found={found?.id === item.id}
      navigate={navigate}
      onMark={changeMark}
    />
  );

  return withToast(
    <>
      <Header title={`안녕하세요, ${me.display_name}님`} subtitle="나에게 맞는 기회와 이번 주 할 일을 한눈에 확인하세요." />
      <FeedSummary counts={shownCounts} selected={summaryFilter} onToggle={toggleSummary} />
      <section ref={listRef}>
        <div className="flex items-center justify-between gap-3">
          <FeedTabs
            tab={tab}
            counts={tabCounts}
            arrived={arrived}
            onArrivedEnd={(done) => setArrived((current) => (current?.id === done.id ? null : current))}
            onSelect={selectTab}
          />
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as NonNullable<FeedParams["sort"]>)}
            className="bg-transparent text-[13px] font-medium text-[#667085] outline-none"
          >
            <option value="deadline">마감 임박순</option>
            <option value="recent">최신순</option>
          </select>
        </div>
        <CategoryChips value={category} onChange={setCategory} />
        {empty ? (
          <EmptyBox {...empty} />
        ) : (
          // 쪽을 넘기면 그 목록의 첫 카드에 초점을 둔다(묶음 카드는 목록 카드 뒤에 있다)
          <FeedList
            listKey={listKey}
            main={main}
            group={group}
            groupTotal={ineligibleItems.length}
            showGroup={showIneligible}
            onToggleGroup={() => setShowIneligible((value) => !value)}
            onPage={(page) => {
              setPageAt({ key: listKey, page });
              cardFocus.current = { kind: "page", index: 0 };
            }}
            onGroupPage={(page) => {
              setGroupPageAt({ key: listKey, page });
              cardFocus.current = { kind: "page", index: main.items.length };
            }}
            card={card}
          />
        )}
      </section>
    </>,
  );
}
