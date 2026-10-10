import { getPlannerTaskMeta } from "@/lib/planner";
import type { PlannerResponse } from "@/types/api";

interface PlannerCalendarProps {
  year: number;
  month: number;
  planner: PlannerResponse;
  selectedDate: string;
  onSelectDate: (date: string) => void;
  onMonthChange: (year: number, month: number) => void;
}

const pad = (value: number) => String(value).padStart(2, "0");

// 연도가 바뀌어도 맞도록 Date.UTC로 6주(42칸)를 만든다
function calendarCells(year: number, month: number) {
  const firstWeekday = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(Date.UTC(year, month - 1, 1 + index - firstWeekday));
    return {
      day: date.getUTCDate(),
      date: `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`,
      dim: date.getUTCMonth() !== month - 1,
    };
  });
}

export default function PlannerCalendar({
  year,
  month,
  planner,
  selectedDate,
  onSelectDate,
  onMonthChange,
}: PlannerCalendarProps) {
  const cells = calendarCells(year, month);
  const changeMonth = (delta: number) => {
    const next = new Date(Date.UTC(year, month - 1 + delta, 1));
    const nextYear = next.getUTCFullYear();
    const nextMonth = next.getUTCMonth() + 1;
    onMonthChange(nextYear, nextMonth);
    onSelectDate(`${nextYear}-${pad(nextMonth)}-01`);
  };

  return (
    <div className="min-h-[650px] rounded-2xl border border-[#e5e7eb] bg-white p-[22px]">
      <div className="flex items-center justify-between">
        <h2 className="text-[22px] font-bold">{year}년 {month}월</h2>
        <div className="flex gap-2">
          <button type="button" aria-label="이전 달" onClick={() => changeMonth(-1)} className="size-9 rounded-[10px] bg-[#f7f8fa] text-[22px] font-semibold text-[#667085]">‹</button>
          <button type="button" aria-label="다음 달" onClick={() => changeMonth(1)} className="size-9 rounded-[10px] bg-[#f7f8fa] text-[22px] font-semibold text-[#667085]">›</button>
        </div>
      </div>
      <div className="mt-[18px] grid grid-cols-7 text-center text-[12px] font-semibold text-[#667085]">
        {["일", "월", "화", "수", "목", "금", "토"].map((day, index) => (
          <div key={day} className={`h-[34px] ${index === 0 ? "text-[#c53030]" : ""}`}>{day}</div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {cells.map((cell, index) => {
          const tasks = planner.items.filter((task) => task.due_date === cell.date);
          const markers = planner.markers.filter((marker) => marker.date === cell.date);
          const selected = cell.date === selectedDate;
          return (
            <button
              type="button"
              key={cell.date}
              onClick={() => onSelectDate(cell.date)}
              className={`h-20 min-w-0 overflow-hidden rounded-[10px] p-1.5 text-left text-[13px] ${
                selected ? "bg-[#eef2ff]" : ""
              }`}
            >
              <span className={`block font-medium ${cell.dim ? "text-[#a0a4ab]" : index % 7 === 0 ? "text-[#c53030]" : selected ? "font-bold text-[#4f6ef7]" : ""}`}>
                {cell.day}
              </span>
              {[...tasks.slice(0, 2).map((task) => ({
                id: task.id,
                label: getPlannerTaskMeta(task).label,
                className: getPlannerTaskMeta(task).chipClass,
              })), ...markers.map((marker) => ({
                id: marker.opportunity_id,
                label: `${getPlannerTaskMeta({
                  id: "",
                  title: "",
                  due_date: marker.date,
                  is_done: false,
                  source: "prep_plan",
                  link: { type: "opportunity", id: marker.opportunity_id, title: marker.title, category: marker.category },
                }).label} 마감`,
                className: "border border-[#4f6ef7] bg-white text-[#4f6ef7]",
              }))].slice(0, 3).map((chip) => (
                <span key={chip.id} className={`mt-1 block w-fit max-w-full truncate rounded-md px-1.5 py-[3px] text-[9px] font-semibold ${chip.className}`}>
                  {chip.label}
                </span>
              ))}
            </button>
          );
        })}
      </div>
    </div>
  );
}
