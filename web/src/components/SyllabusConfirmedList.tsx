import { useEffect } from "react";
import Button from "@/components/Button";
import { ITEM_LABELS } from "@/components/SyllabusReviewTable";
import { formatKstLongDate, getKstTimeKey } from "@/lib/format";
import useFocusHandoff from "@/lib/useFocusHandoff";
import type { SyllabusItemView } from "@/types/api";

// 확정한 계획서 일정 목록 (F-14). 이 탭의 평소 모습이다.
// 캘린더는 확정할 때 함께 넣는 것이 보통이고, 그때 연결하지 않았으면 여기서 하나씩 넣는다

interface SyllabusConfirmedListProps {
  items: SyllabusItemView[];
  waiting: number; // 확인하지 않은 일정 수
  canReview: boolean; // 계획서 번호를 알아 확인 화면을 다시 열 수 있다
  calendarConnected: boolean;
  added: string[]; // 이 화면에서 방금 넣은 일정(서버가 준 calendar_registered와 합쳐 본다)
  busyItem: string | null;
  onAddToCalendar: (item: SyllabusItemView) => void;
  onConnectCalendar: () => void;
  onReview: () => void;
  onUpload: () => void;
}

export default function SyllabusConfirmedList({
  items,
  waiting,
  canReview,
  calendarConnected,
  added,
  busyItem,
  onAddToCalendar,
  onConnectCalendar,
  onReview,
  onUpload,
}: SyllabusConfirmedListProps) {
  // 넣고 나면 버튼이 "캘린더에 넣었어요"로 바뀌어 사라진다. 초점이 <body>로 빠지지 않게 그 글로 넘긴다
  const handoff = useFocusHandoff();
  const { cancel } = handoff;
  // 넣지 못하고 끝나면(버튼이 남음) 기억을 지운다. 그대로 두면 나중에 다른 길로 "넣었어요"가 될 때 초점을 가져간다
  useEffect(() => {
    if (busyItem === null) cancel();
  }, [busyItem, cancel]);
  return (
    <>
      {items.length === 0 && (
        <p className="mb-4 rounded-[10px] bg-[#fff8e1] px-4 py-3 text-[13px] text-[#b7791f]">
          아직 플래너에 넣은 일정이 없어요.
          {canReview ? " 뽑아 둔 일정을 확인하면 플래너에 들어가요." : " 계획서를 올려 주세요."}
        </p>
      )}
      <ul className="flex flex-col gap-3">
        {items.map((item) => (
          <li
            key={item.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-[12px] bg-[#f7f8fa] p-4"
          >
            <div>
              <p className="text-[12px] font-semibold text-[#4f6ef7]">
                {ITEM_LABELS[item.item_type]}
              </p>
              <p className="mt-1 text-[14px] font-semibold">{item.title}</p>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[12px] text-[#667085]">
                {item.starts_at
                  ? `${formatKstLongDate(item.starts_at)} ${getKstTimeKey(item.starts_at)}`
                  : "일정 미정"}
              </span>
              {added.includes(item.id) || item.calendar_registered ? (
                <span
                  ref={handoff.target(item.id)}
                  tabIndex={-1}
                  className="text-[12px] font-semibold text-[#15803d] outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f6ef7]"
                >
                  캘린더에 넣었어요
                </span>
              ) : (
                item.starts_at &&
                (calendarConnected ? (
                  <button
                    type="button"
                    // 넣는 동안 disabled로 막으면 초점이 빠진다. aria-disabled로 알리고 누름은 무시한다
                    onClick={() => {
                      if (busyItem !== null) return;
                      handoff.mark(item.id);
                      onAddToCalendar(item);
                    }}
                    aria-disabled={busyItem !== null || undefined}
                    aria-busy={busyItem === item.id || undefined}
                    className="text-[12px] font-semibold text-[#4f6ef7] aria-disabled:not-aria-busy:cursor-default aria-disabled:text-[#a0a4ab] aria-busy:cursor-wait"
                  >
                    {busyItem === item.id ? "넣는 중…" : "캘린더에 넣기"}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={onConnectCalendar}
                    className="text-[12px] font-semibold text-[#4f6ef7]"
                  >
                    캘린더 연결하기
                  </button>
                ))
              )}
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[12px] text-[#667085]">
          {waiting > 0 && canReview
            ? `확인하지 않은 일정이 ${waiting}건 있어요.`
            : "계획서를 다시 올리면 지금 일정을 새 계획서로 바꿔요."}
        </p>
        <div className="flex gap-2">
          {waiting > 0 && canReview && (
            <Button onClick={onReview}>{waiting}건 확인하기</Button>
          )}
          <button
            type="button"
            onClick={onUpload}
            className="h-[38px] rounded-[10px] border border-[#e5e7eb] px-4 text-[13px] font-semibold"
          >
            계획서 다시 올리기
          </button>
        </div>
      </div>
    </>
  );
}
