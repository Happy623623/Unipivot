import Badge from "@/components/Badge";
import Button from "@/components/Button";
import { formatKstShortDate } from "@/lib/format";
import type { PrepareResult, ProcessStep } from "@/types/api";

// 준비하기 실행의 단계(API 명세 11장). 도구 이름으로 맞춰 서버가 label을 바꿔도 따라간다.
// 서버가 단계를 주기 전까지는 이 순서로 대기를 보여 주고, 서버가 준 label이 있으면 그 글을 쓴다
const STEPS = [
  { tool: "get_document_guide", label: "필요 서류 확인" },
  { tool: "build_prep_plan", label: "마감일에서 거꾸로 일정 짜기" },
];

interface PreparationProgressProps {
  steps: ProcessStep[] | null; // null이면 아직 누르지 않았다
  result: PrepareResult | null;
  calendarConnected: boolean;
  hasDeadline: boolean; // 상시 공고는 캘린더에 넣을 마감일이 없다
  includeCalendar: boolean;
  onIncludeCalendar: (include: boolean) => void;
  onConnectCalendar: () => void;
  finishing: boolean;
  onFinish: () => void;
}

function stepBadge(step: ProcessStep | undefined) {
  if (step?.status === "succeeded") return <Badge tone="green">완료</Badge>;
  if (step?.status === "failed") return <Badge tone="red">실패</Badge>;
  if (step?.status === "running") return <Badge tone="blue">진행 중</Badge>;
  return <Badge tone="gray">대기</Badge>;
}

// 준비 일정 생성의 진행 단계와 만들어진 할 일. 캘린더 등록(F-32)은 아직이라 실제 모드에서는 끈다
export default function PreparationProgress({
  steps,
  result,
  calendarConnected,
  hasDeadline,
  includeCalendar,
  onIncludeCalendar,
  onConnectCalendar,
  finishing,
  onFinish,
}: PreparationProgressProps) {
  return (
    <>
      {steps && (
        <section className="rounded-[14px] border border-[#e5e7eb] bg-white p-[18px]">
          <h2 className="text-[15px] font-semibold">준비 일정 생성</h2>
          <div className="mt-3 flex flex-col gap-2">
            {STEPS.map(({ tool, label }) => {
              const step = steps.find((current) => current.tool === tool);
              return (
                <div
                  key={tool}
                  className="flex items-center justify-between rounded-[10px] bg-[#f7f8fa] px-4 py-3 text-[13px]"
                >
                  <span>{step?.label ?? label}</span>
                  {stepBadge(step)}
                </div>
              );
            })}
          </div>
        </section>
      )}
      {result && (
        <section className="rounded-[14px] border border-[#cfd7ff] bg-white p-[18px]">
          <h2 className="text-[16px] font-semibold">준비 일정을 만들었어요</h2>
          <div className="mt-3 flex flex-col gap-2">
            {result.tasks.map((task) => (
              <div
                key={task.id}
                className="flex justify-between rounded-[10px] bg-[#f7f8fa] px-4 py-3 text-[13px]"
              >
                <span>{task.title}</span>
                <span className="text-[#667085]">{formatKstShortDate(task.due_date)}</span>
              </div>
            ))}
          </div>
          {hasDeadline && (
            <>
              <label className="mt-4 flex items-center gap-2 text-[13px] font-medium">
                <input
                  type="checkbox"
                  checked={includeCalendar}
                  onChange={(event) => onIncludeCalendar(event.target.checked)}
                  className="accent-[#4f6ef7]"
                />
                마감일을 Google Calendar에도 넣기
              </label>
              {includeCalendar && !calendarConnected && (
                <p className="mt-2 text-[12px] text-[#667085]">
                  완료를 누르면 Google 화면에서 캘린더 권한을 먼저 받아요.{" "}
                  <button type="button" onClick={onConnectCalendar} className="font-semibold text-[#4f6ef7]">
                    지금 연결하기
                  </button>
                </p>
              )}
            </>
          )}
          {result.calendar_error && (
            <p className="mt-2 text-[12px] text-[#c53030]">{result.calendar_error}</p>
          )}
          <div className="mt-4 flex justify-end">
            <Button onClick={onFinish} disabled={finishing}>
              {finishing ? "완료 중" : "완료"}
            </Button>
          </div>
        </section>
      )}
    </>
  );
}
