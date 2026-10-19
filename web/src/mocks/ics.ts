import { icsQuery } from "@/lib/ics";
import type { PlannerResponse } from "@/types/api";

// 목 모드의 .ics 미리보기. 서버가 주는 파일의 축소판이다(일정은 그날 18:00 KST로 끝나는 1시간, 줄 접기 없음)
export function mockIcs(planner: PlannerResponse, today: string): string {
  const query = new URLSearchParams(icsQuery(planner, today) ?? "");
  const chosen = (name: string) => new Set((query.get(name) ?? "").split(",").filter(Boolean));
  const opportunities = chosen("opportunity_ids");
  const assignments = chosen("lms_assignment_ids");
  const syllabusItems = chosen("syllabus_item_ids");
  const events = [
    ...planner.markers
      .filter((m) => opportunities.has(m.opportunity_id))
      .map((m) => ({ uid: `opportunity-${m.opportunity_id}@unipivot`, title: `[마감] ${m.title.replace(/ 마감$/, "")}`, date: m.date })),
    ...planner.items
      .filter((t) => t.link.id !== null && assignments.has(t.link.id))
      .map((t) => ({ uid: `lms_assignment-${t.link.id}@unipivot`, title: `[과제] ${t.link.title} · ${t.title}`, date: t.due_date })),
    ...planner.items
      .filter((t) => t.link.id !== null && syllabusItems.has(t.link.id))
      .map((t) => ({ uid: `syllabus_item-${t.link.id}@unipivot`, title: `[일정] ${t.link.title} · ${t.title}`, date: t.due_date })),
  ];
  const stamp = (date: string, hour: string) => `${date.replace(/-/g, "")}T${hour}0000Z`; // 18:00 KST = 09:00Z
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//UNIPIVOT//UNIPIVOT Calendar//KO", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"];
  for (const event of events) {
    lines.push("BEGIN:VEVENT", `UID:${event.uid}`, `DTSTAMP:${stamp(today, "00")}`, `DTSTART:${stamp(event.date, "08")}`, `DTEND:${stamp(event.date, "09")}`, `SUMMARY:${event.title}`, "END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n") + "\r\n";
}
