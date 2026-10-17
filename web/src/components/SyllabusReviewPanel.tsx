import Button from "@/components/Button";
import SyllabusReviewTable, { type ReviewRow } from "@/components/SyllabusReviewTable";

// 계획서 확인 화면 (F-14). 표 + 캘린더 선택 + 넣기·그만두기.
// 그만두기를 둔다 — 일정을 하나도 못 찾은 계획서에서 빠져나갈 길이 있어야 한다

interface SyllabusReviewPanelProps {
  rows: ReviewRow[];
  problems: Record<string, string>; // 422 항목 오류(items.0.title 꼴)
  saving: boolean;
  connected: boolean; // Google 캘린더 연결 여부
  withCalendar: boolean;
  onRows: (rows: ReviewRow[]) => void;
  onWithCalendar: (on: boolean) => void;
  onConnect: () => void;
  onCancel: () => void;
  onSave: () => void;
}

export default function SyllabusReviewPanel({
  rows,
  problems,
  saving,
  connected,
  withCalendar,
  onRows,
  onWithCalendar,
  onConnect,
  onCancel,
  onSave,
}: SyllabusReviewPanelProps) {
  const chosen = rows.filter((row) => row.selected).length;
  const label = chosen === 0
    ? "플래너에 넣기"
    : withCalendar
      ? `${chosen}건 플래너·캘린더에 넣기`
      : `${chosen}건 플래너에 넣기`;

  return (
    <>
      <p className="mb-4 text-[13px] text-[#667085]">
        뽑은 일정을 확인해 주세요. 주차만 적힌 계획서는 날짜가 하루 이틀 어긋날 수 있어요.
      </p>
      <SyllabusReviewTable rows={rows} disabled={saving} problems={problems} onChange={onRows} />
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        {connected ? (
          <label className="flex items-center gap-2 text-[13px] font-semibold text-[#344054]">
            <input
              type="checkbox"
              checked={withCalendar}
              disabled={saving}
              onChange={(event) => onWithCalendar(event.target.checked)}
              className="h-4 w-4 accent-[#4f6ef7]"
            />
            구글 캘린더에도 넣기
          </label>
        ) : (
          <button
            type="button"
            onClick={onConnect}
            className="text-[13px] font-semibold text-[#4f6ef7]"
          >
            구글 캘린더 연결하기
          </button>
        )}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="h-[42px] rounded-[10px] border border-[#e5e7eb] px-[18px] text-[14px] font-semibold"
          >
            그만두기
          </button>
          <Button onClick={onSave} disabled={chosen === 0 || saving}>
            {saving ? "넣는 중…" : label}
          </Button>
        </div>
      </div>
    </>
  );
}
