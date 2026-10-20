import { ApiError, errorMessage } from "@/api/client";
import Button from "@/components/Button";

// 캘린더만 실패했을 때. 준비 일정은 이미 만들어져 있다는 것을 같이 알린다
export function calendarFailure(error: unknown): string {
  const reason =
    error instanceof ApiError && error.code === "CALENDAR_NOT_CONNECTED"
      ? "Google 캘린더 권한이 없어요. 설정에서 연결해 주세요."
      : errorMessage(error, "마감일을 캘린더에 넣지 못했어요. 잠시 후 다시 눌러 주세요.");
  return `${reason} 준비 일정은 플래너에 그대로 있어요.`;
}

interface DeadlineCalendarRowProps {
  registered: boolean;
  busy: boolean;
  onToggle: () => void;
}

// 준비한 공고의 마감일을 Google Calendar에 넣고 빼는 줄 (F-32).
// 준비하기 결과 창에서 넣지 않았거나, 넣은 뒤 다시 빼고 싶을 때 쓴다
export default function DeadlineCalendarRow({ registered, busy, onToggle }: DeadlineCalendarRowProps) {
  return (
    <section className="flex items-center justify-between gap-4 rounded-[14px] border border-[#e5e7eb] bg-white p-[18px]">
      <div>
        <p className="text-[14px] font-semibold">마감일 캘린더</p>
        <p className="mt-1 text-[12px] text-[#667085]">
          {registered
            ? "Google Calendar에 마감 1시간 전 일정으로 들어가 있어요."
            : "마감일을 Google Calendar에 넣어 두면 캘린더 알림으로도 받아요."}
        </p>
      </div>
      <Button secondary onClick={onToggle} busy={busy}>
        {registered ? "캘린더에서 빼기" : "캘린더에 넣기"}
      </Button>
    </section>
  );
}
