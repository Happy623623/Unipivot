import { useState } from "react";
import {
  errorMessage,
  getOpportunity,
  prepareOpportunity,
  PREPARE_NOT_READY,
  PREPARE_READY,
  todayKst,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button, { ButtonLink } from "@/components/Button";
import Modal from "@/components/Modal";
import StatusBadge from "@/components/StatusBadge";
import {
  formatKstDate,
  formatKstShortDate,
  getDdayValue,
  isDeadlineSoon,
} from "@/lib/format";
import type { OpportunityDetail, PrepareResult } from "@/types/api";
import type { Route } from "@/types/route";

interface OpportunityPreparationProps {
  detail: OpportunityDetail;
  calendarConnected: boolean;
  navigate: (route: Route) => void;
  onOpenProfile: () => void;
  originalHref: string | null; // 공고 원문 주소(http·https만)
  onOpenPoster: (() => void) | null; // 포스터 원본 이미지가 있으면 창으로 연다
  onDetailChange: (detail: OpportunityDetail) => void;
}

type StepStatus = "idle" | "running" | "done";

const wait = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

function deadlineCopy(detail: OpportunityDetail): string {
  const days = getDdayValue(detail.deadline_at, todayKst());
  if (days === null) return "상시 모집";
  if (days === 0) return "오늘 마감";
  if (days > 0) return `마감까지 ${days}일`;
  return "마감됨";
}

export default function OpportunityPreparation({
  detail,
  calendarConnected,
  navigate,
  onOpenProfile,
  originalHref,
  onOpenPoster,
  onDetailChange,
}: OpportunityPreparationProps) {
  const [steps, setSteps] = useState<[StepStatus, StepStatus]>(["idle", "idle"]);
  const [result, setResult] = useState<PrepareResult | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [includeCalendar, setIncludeCalendar] = useState(true);
  const [finishing, setFinishing] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [targetDate, setTargetDate] = useState(""); // 상시 공고의 준비 목표일
  const [message, setMessage] = useState<string | null>(null); // 준비하기를 하지 못한 이유
  const today = todayKst();
  const deadlineSoon = isDeadlineSoon(detail.deadline_at, today);
  const applicationPeriod = `${detail.apply_start_at ? formatKstDate(detail.apply_start_at) : "시작일 미정"} ~ ${
    detail.deadline_at ? formatKstDate(detail.deadline_at) : "상시"
  }`;

  // 실제 모드는 아직 준비하기 API가 없어 누르면 바로 준비 중이라고 알린다(목표일·확인 창 없이)
  const notReady = () => setMessage(PREPARE_NOT_READY);

  // 목 모드: 단계 진행을 흉내 낸다. TODO(api): 준비하기 API가 생기면 waitForRun의 steps로 바꾼다
  const startPreparation = async () => {
    setConfirmOpen(false);
    setCompleted(false);
    setResult(null);
    setMessage(null);
    setSteps(["running", "idle"]);
    try {
      await wait(600);
      setSteps(["done", "running"]);
      const [prepared] = await Promise.all([
        prepareOpportunity(detail.id, false, targetDate || undefined),
        wait(600),
      ]);
      setSteps(["done", "done"]);
      setResult(prepared);
      onDetailChange(await getOpportunity(detail.id));
    } catch (error) {
      setSteps(["idle", "idle"]);
      setMessage(errorMessage(error, "준비 일정을 만들지 못했어요. 잠시 후 다시 눌러 주세요."));
    }
  };

  const finishPreparation = async () => {
    setFinishing(true);
    if (includeCalendar && calendarConnected) {
      await prepareOpportunity(detail.id, true, targetDate || undefined);
    }
    const updated = await getOpportunity(detail.id);
    onDetailChange(updated);
    setFinishing(false);
    setCompleted(true);
  };

  const action = (() => {
    if (result) {
      return <Badge tone="green">일정 생성 완료</Badge>;
    }
    if (detail.prep.prepared && !result) {
      const progress =
        detail.prep.tasks_total > 0
          ? (detail.prep.tasks_done / detail.prep.tasks_total) * 100
          : 0;
      return (
        <div className="w-[210px]">
          <div className="flex justify-between text-[12px] font-semibold">
            <span>서류 {detail.prep.tasks_done}/{detail.prep.tasks_total} 완료</span>
            <button type="button" onClick={() => navigate({ name: "planner" })} className="text-[#4f6ef7]">
              플래너에서 보기
            </button>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#e5e7eb]">
            <div className="h-full rounded-full bg-[#4f6ef7]" style={{ width: `${progress}%` }} />
          </div>
        </div>
      );
    }
    if (detail.eligibility.display_status === "eligible") {
      if (!PREPARE_READY) return <Button onClick={notReady}>준비 일정 만들기</Button>;
      if (!detail.deadline_at) {
        return (
          <div className="flex items-end gap-2">
            <label className="text-[12px] font-semibold text-[#667085]">
              목표일
              <input
                type="date"
                value={targetDate}
                min={today}
                onChange={(event) => setTargetDate(event.target.value)}
                className="mt-1 block h-[42px] rounded-[10px] border border-[#e5e7eb] px-3 text-[14px] text-[#181a20]"
              />
            </label>
            <Button onClick={startPreparation} disabled={!targetDate}>준비 일정 만들기</Button>
          </div>
        );
      }
      return <Button onClick={startPreparation}>준비 일정 만들기</Button>;
    }
    if (detail.eligibility.display_status === "missing_info") {
      return <Button onClick={onOpenProfile}>정보 입력</Button>;
    }
    if (detail.eligibility.display_status === "needs_review") {
      if (originalHref) return <ButtonLink href={originalHref}>원문 보기</ButtonLink>;
      return (
        <Button onClick={onOpenPoster ?? undefined} disabled={!onOpenPoster} title={onOpenPoster ? undefined : "원문 주소가 없어요"}>
          원문 보기
        </Button>
      );
    }
    return (
      <div className="flex gap-2">
        <span title="대체 공고 추천은 준비 중이에요">
          <Button disabled>대체 공고 보기</Button>
        </span>
        <Button secondary onClick={PREPARE_READY ? () => setConfirmOpen(true) : notReady}>그래도 준비하기</Button>
      </div>
    );
  })();

  return (
    <>
      <section className="flex items-center justify-between gap-5 rounded-2xl border border-[#e5e7eb] bg-white p-[22px] max-[760px]:flex-col max-[760px]:items-start">
        <div>
          <div className="flex gap-2">
            <StatusBadge displayStatus={detail.eligibility.display_status} />
            {detail.needs_review && detail.eligibility.display_status === "eligible" && (
              <Badge tone="gray">원문 확인 필요</Badge>
            )}
          </div>
          <p className="mt-2 text-[16px] font-semibold">{detail.eligibility.reason_text}</p>
          <p className={`mt-2 text-[13px] ${deadlineSoon ? "font-semibold text-[#c53030]" : "text-[#667085]"}`}>
            {deadlineCopy(detail)}
          </p>
          <p className="mt-1 text-[12px] text-[#667085]">신청 기간 {applicationPeriod}</p>
        </div>
        {action}
      </section>
      {message && (
        <p role="status" className="rounded-[10px] bg-[#f2f4f7] px-4 py-3 text-[13px] text-[#475467]">{message}</p>
      )}
      {steps[0] !== "idle" && (
        <section className="rounded-[14px] border border-[#e5e7eb] bg-white p-[18px]">
          <h2 className="text-[15px] font-semibold">준비 일정 생성</h2>
          <div className="mt-3 flex flex-col gap-2">
            {["필요 서류 확인", "마감일에서 거꾸로 일정 짜기"].map((label, index) => (
              <div key={label} className="flex items-center justify-between rounded-[10px] bg-[#f7f8fa] px-4 py-3 text-[13px]">
                <span>{label}</span>
                <Badge tone={steps[index] === "done" ? "green" : "blue"}>
                  {steps[index] === "done" ? "완료" : steps[index] === "running" ? "진행 중" : "대기"}
                </Badge>
              </div>
            ))}
          </div>
        </section>
      )}
      {result && (
        <section className="rounded-[14px] border border-[#cfd7ff] bg-white p-[18px]">
          <h2 className="text-[16px] font-semibold">준비 일정을 만들었어요</h2>
          <div className="mt-3 flex flex-col gap-2">
            {result.tasks.map((task) => (
              <div key={task.id} className="flex justify-between rounded-[10px] bg-[#f7f8fa] px-4 py-3 text-[13px]">
                <span>{task.title}</span>
                <span className="text-[#667085]">{formatKstShortDate(task.due_date)}</span>
              </div>
            ))}
          </div>
          <label className="mt-4 flex items-center gap-2 text-[13px] font-medium">
            <input
              type="checkbox"
              checked={includeCalendar && calendarConnected}
              disabled={!calendarConnected}
              onChange={(event) => setIncludeCalendar(event.target.checked)}
              className="accent-[#4f6ef7]"
            />
            마감일을 Google Calendar에도 넣기
          </label>
          {!calendarConnected && <p className="mt-2 text-[12px] text-[#667085]">설정에서 Google Calendar를 연결하면 함께 넣을 수 있어요</p>}
          <div className="mt-4 flex justify-end">
            <Button onClick={finishPreparation} disabled={finishing}>
              {finishing ? "완료 중" : "완료"}
            </Button>
          </div>
        </section>
      )}
      {completed && (
        <div className="fixed bottom-6 left-1/2 z-[90] flex -translate-x-1/2 items-center gap-3 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          준비 일정을 만들었어요
          <button type="button" onClick={() => navigate({ name: "planner" })} className="text-[#cfd7ff]">
            플래너에서 보기
          </button>
        </div>
      )}
      <Modal open={confirmOpen} title="그래도 준비하기" onClose={() => setConfirmOpen(false)}>
        <p className="text-[14px] leading-6 text-[#344054]">
          지원 조건을 충족하지 못한 공고예요. 그래도 준비 일정을 만들까요?
        </p>
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setConfirmOpen(false)}>취소</Button>
          <Button onClick={startPreparation}>그래도 만들기</Button>
        </div>
      </Modal>
    </>
  );
}
