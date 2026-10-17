import { getKstDateKey, getKstTimeKey } from "@/lib/format";
import type { SyllabusItemType, SyllabusItemView } from "@/types/api";

// 계획서 확인 화면의 표 (F-14). 뽑은 일정을 고치고 플래너·캘린더에 넣을 것만 고른다.
// 제목·날짜·시각을 모두 고칠 수 있다 — 모델이 센 날짜는 하루 이틀 어긋날 수 있다(명세 8장)

export const ITEM_LABELS: Record<SyllabusItemType, string> = {
  midterm: "중간",
  final: "기말",
  presentation: "발표",
  assignment: "과제",
  etc: "기타",
};

// 화면이 들고 있는 한 줄. 날짜·시각은 입력 칸 값이라 글자로 둔다
export interface ReviewRow {
  id: string;
  item_type: SyllabusItemType;
  title: string;
  date: string; // YYYY-MM-DD (비어 있으면 날짜 미정)
  time: string; // HH:MM
  selected: boolean;
}

// 뽑은 일정을 표의 줄로. 날짜가 없는 일정은 빈 칸으로 두고 고르지 않은 상태로 시작한다
export function toReviewRows(items: SyllabusItemView[]): ReviewRow[] {
  return items.map((item) => ({
    id: item.id,
    item_type: item.item_type,
    title: item.title,
    date: item.starts_at ? getKstDateKey(item.starts_at) : "",
    time: item.starts_at ? getKstTimeKey(item.starts_at) : "09:00",
    selected: item.starts_at !== null,
  }));
}

interface SyllabusReviewTableProps {
  rows: ReviewRow[];
  disabled: boolean;
  problems: Record<string, string>; // 서버가 준 항목 오류(`items.0.title` 꼴)
  onChange: (rows: ReviewRow[]) => void;
}

export default function SyllabusReviewTable({
  rows,
  disabled,
  problems,
  onChange,
}: SyllabusReviewTableProps) {
  const update = (id: string, patch: Partial<ReviewRow>) =>
    onChange(rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));

  // 서버는 보낸 순서로 `items.2.title`처럼 알려 준다. 그 줄 아래에 보여 준다
  const problemOf = (index: number) =>
    Object.entries(problems).find(([key]) => key.startsWith(`items.${index}.`))?.[1];

  return (
    <ul className="flex flex-col gap-3">
      {rows.map((row, index) => (
        <li
          key={row.id}
          className={`rounded-[12px] border p-4 ${
            row.selected ? "border-[#cfd7ff] bg-[#f7f8fa]" : "border-[#e5e7eb] bg-white"
          }`}
        >
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-[13px] font-semibold">
              <input
                type="checkbox"
                checked={row.selected}
                disabled={disabled}
                onChange={(event) => update(row.id, { selected: event.target.checked })}
                className="h-4 w-4 accent-[#4f6ef7]"
                aria-label={`${row.title} 플래너에 넣기`}
              />
              <span className="rounded-full bg-[#eef2ff] px-2 py-[2px] text-[12px] text-[#4f6ef7]">
                {ITEM_LABELS[row.item_type]}
              </span>
            </label>
            <input
              type="text"
              value={row.title}
              disabled={disabled}
              onChange={(event) => update(row.id, { title: event.target.value })}
              aria-label={`일정 ${index + 1} 이름`}
              aria-invalid={problemOf(index) !== undefined}
              className="min-w-[160px] flex-1 rounded-[8px] border border-[#e5e7eb] px-3 py-2 text-[14px] font-semibold"
            />
            <input
              type="date"
              value={row.date}
              disabled={disabled}
              onChange={(event) => update(row.id, { date: event.target.value })}
              aria-label={`${row.title} 날짜`}
              aria-invalid={row.selected && !row.date}
              aria-describedby={row.selected && !row.date ? `syllabus-${row.id}-problem` : undefined}
              className="rounded-[8px] border border-[#e5e7eb] px-2 py-2 text-[13px]"
            />
            <input
              type="time"
              value={row.time}
              disabled={disabled}
              onChange={(event) => update(row.id, { time: event.target.value })}
              aria-label={`${row.title} 시각`}
              aria-invalid={row.selected && !row.time}
              className="rounded-[8px] border border-[#e5e7eb] px-2 py-2 text-[13px]"
            />
          </div>
          {row.selected && (!row.date || !row.time) && (
            <p id={`syllabus-${row.id}-problem`} className="mt-2 text-[12px] text-[#c53030]">
              {row.date
                ? "시각을 적어 주세요. 비워 두면 넣을 수 없어요."
                : "날짜를 적어 주세요. 날짜가 없는 일정은 넣을 수 없어요."}
            </p>
          )}
          {problemOf(index) && (
            <p className="mt-2 text-[12px] text-[#c53030]">{problemOf(index)}</p>
          )}
        </li>
      ))}
    </ul>
  );
}
