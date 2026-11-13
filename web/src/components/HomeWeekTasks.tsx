import { getPlanner, todayKst } from "@/api/client";
import Badge from "@/components/Badge";
import Skeleton from "@/components/Skeleton";
import { daysLater } from "@/lib/ics";
import { getPlannerTaskMeta, plannerTaskRoute } from "@/lib/planner";
import useAsyncData from "@/lib/useAsyncData";
import type { PlannerMarker, PlannerResponse, PlannerTask } from "@/types/api";
import type { Route } from "@/types/route";

// 홈 '이번 주 할 일'(피드백 4①). 플래너와 같은 API로 오늘부터 7일 안의 할 일과 준비 중인 공고 마감을 모아
// 날짜순으로 몇 개만 보인다. 누르면 출처(공고 상세·과목 탭)로 가고, 나머지는 플래너에서 본다
const WEEK_DAYS = 6; // 오늘 + 6일
export const WEEK_SHOWN = 5;

export type WeekEntry =
  | { kind: "task"; date: string; task: PlannerTask }
  | { kind: "deadline"; date: string; marker: PlannerMarker };

// 끝내지 않은 할 일과 마감을 날짜순으로. 같은 날이면 마감을 먼저 둔다(놓치면 되돌릴 수 없다)
export function weekEntries(planner: PlannerResponse): WeekEntry[] {
  const entries: WeekEntry[] = [
    ...planner.markers.map((marker) => ({ kind: "deadline" as const, date: marker.date, marker })),
    ...planner.items
      .filter((task) => !task.is_done)
      .map((task) => ({ kind: "task" as const, date: task.due_date, task })),
  ];
  const rank = (entry: WeekEntry) => (entry.kind === "deadline" ? 0 : 1);
  const title = (entry: WeekEntry) => (entry.kind === "deadline" ? entry.marker.title : entry.task.title);
  return entries.sort(
    (a, b) => a.date.localeCompare(b.date) || rank(a) - rank(b) || title(a).localeCompare(title(b), "ko"),
  );
}

// "오늘" · "내일" · "11/15 (토)"
export function weekDayLabel(date: string, today: string): string {
  if (date === today) return "오늘";
  if (date === daysLater(today, 1)) return "내일";
  const weekday = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", weekday: "short" }).format(
    new Date(`${date}T00:00:00+09:00`),
  );
  return `${Number(date.slice(5, 7))}/${Number(date.slice(8, 10))} (${weekday})`;
}

function entryRoute(entry: WeekEntry): Route | null {
  if (entry.kind === "deadline") return { name: "opportunity", id: entry.marker.opportunity_id };
  return plannerTaskRoute(entry.task);
}

function EntryLine({ entry, today }: { entry: WeekEntry; today: string }) {
  const when = weekDayLabel(entry.date, today);
  if (entry.kind === "deadline") {
    return (
      <>
        <span className="min-w-0">
          <span className="block text-[12px] text-[#667085]">{when}</span>
          {/* 마커 제목은 서버가 "… 마감"으로 준다 */}
          <b className="block truncate text-[14px] font-semibold">{entry.marker.title}</b>
        </span>
        <Badge tone="red">마감</Badge>
      </>
    );
  }
  const meta = getPlannerTaskMeta(entry.task);
  return (
    <>
      <span className="min-w-0">
        <span className="block text-[12px] text-[#667085]">{when}</span>
        <b className="block truncate text-[14px] font-semibold">{entry.task.title}</b>
      </span>
      <Badge tone={meta.tone}>{meta.label}</Badge>
    </>
  );
}

export default function HomeWeekTasks({ navigate }: { navigate: (route: Route) => void }) {
  const today = todayKst();
  const request = useAsyncData(() => getPlanner(today, daysLater(today, WEEK_DAYS)), [today]);
  const entries = request.data ? weekEntries(request.data) : [];
  const shown = entries.slice(0, WEEK_SHOWN);
  const rest = entries.length - shown.length;

  return (
    <section aria-labelledby="home-week-tasks" className="max-w-[786px] rounded-2xl border border-[#e5e7eb] bg-white p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 id="home-week-tasks" className="text-[18px] font-semibold">
          이번 주 할 일 {request.data && <span className="text-[14px] font-medium text-[#667085]">{entries.length}</span>}
        </h2>
        <button type="button" onClick={() => navigate({ name: "planner" })} className="text-[13px] font-semibold text-[#4f6ef7]">
          플래너에서 모두 보기
        </button>
      </div>
      {request.loading ? (
        <div className="mt-3 flex flex-col gap-2">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : request.error ? (
        // 할 일을 못 받아도 공고 목록은 그대로 쓴다. 홈 전체를 오류로 바꾸지 않는다
        <p className="mt-3 text-[13px] text-[#c53030]">할 일을 불러오지 못했어요. 플래너에서 확인해 주세요.</p>
      ) : shown.length === 0 ? (
        <p className="mt-3 text-[13px] text-[#667085]">
          7일 안에 할 일이 없어요. 공고를 준비하거나 LearningX를 연결하면 서류·과제 마감이 여기에 모여요.
        </p>
      ) : (
        <ul className="mt-2 flex flex-col">
          {shown.map((entry) => {
            const route = entryRoute(entry);
            const key = entry.kind === "deadline" ? `deadline-${entry.marker.opportunity_id}` : `task-${entry.task.id}`;
            const line = <EntryLine entry={entry} today={today} />;
            const row = "flex w-full items-center justify-between gap-3 rounded-[10px] px-2 py-1.5 text-left";
            return (
              <li key={key}>
                {route ? (
                  <button type="button" onClick={() => navigate(route)} className={`${row} hover:bg-[#f7f8fa]`}>
                    {line}
                  </button>
                ) : (
                  // 직접 추가한 할 일·과목을 모르는 계획서 일정은 갈 곳이 없다. 플래너에서 고친다
                  <div className={row}>{line}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {rest > 0 && <p className="mt-2 px-2 text-[12px] text-[#667085]">그 밖에 {rest}개는 플래너에서 볼 수 있어요.</p>}
    </section>
  );
}
