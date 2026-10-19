import type { PlannerResponse } from "@/types/api";

// .ics 내려받기(F-34)의 대상 고르기. 서버(`GET /calendar/ics`)가 받는 쿼리 문자열을 만든다

// 오늘부터 이만큼 앞까지 받는다. 플래너 조회 상한(400일) 안이다
export const ICS_DAYS = 365;

// "YYYY-MM-DD"에 날을 더한다(KST 날짜 문자열끼리라 시간대가 끼어들지 않는다)
export function daysLater(date: string, days: number): string {
  const base = Date.UTC(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10)));
  return new Date(base + days * 86_400_000).toISOString().slice(0, 10);
}

// 플래너에서 캘린더에 넣을 수 있는 것: 준비를 마친 공고의 마감(마커), 아직 끝내지 않은 LMS 과제와
// 계획서 일정. 오늘보다 앞선 날은 뺀다(서버도 지난 것은 건너뛴다). 받을 게 없으면 null
export function icsQuery(planner: PlannerResponse, today: string): string | null {
  const open = planner.items.filter((task) => !task.is_done && task.due_date >= today);
  const lists: [string, string[]][] = [
    ["opportunity_ids", planner.markers.filter((m) => m.date >= today).map((m) => m.opportunity_id)],
    ["lms_assignment_ids", open.filter((t) => t.link.type === "lms_assignment").map((t) => t.link.id ?? "")],
    ["syllabus_item_ids", open.filter((t) => t.link.type === "syllabus_item").map((t) => t.link.id ?? "")],
  ];
  const query = new URLSearchParams();
  for (const [name, ids] of lists) {
    const given = Array.from(new Set(ids.filter(Boolean)));
    if (given.length) query.set(name, given.join(","));
  }
  const text = query.toString();
  return text ? text : null;
}
