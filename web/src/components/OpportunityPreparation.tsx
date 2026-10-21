import { useEffect, useState } from "react";
import {
  ApiError,
  connectCalendar,
  errorMessage,
  fieldErrors,
  getOpportunity,
  prepareOpportunity,
  todayKst,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button, { ButtonLink } from "@/components/Button";
import DeadlineCalendarRow, { calendarFailure } from "@/components/DeadlineCalendarRow";
import Modal, { ModalDescription } from "@/components/Modal";
import PreparationProgress from "@/components/PreparationProgress";
import StatusBadge from "@/components/StatusBadge";
import { formatKstDate, getDdayValue, isDeadlineSoon } from "@/lib/format";
import useCalendarEvent from "@/lib/useCalendarEvent";
import type { OpportunityDetail, PrepareResult, ProcessStep } from "@/types/api";
import type { Route } from "@/types/route";

interface OpportunityPreparationProps {
  detail: OpportunityDetail;
  calendarConnected: boolean;
  calendarResult: "connected" | "error" | null; // Google 캘린더 연결에서 돌아온 결과
  navigate: (route: Route) => void;
  onOpenProfile: () => void;
  originalHref: string | null; // 공고 원문 주소(http·https만)
  onOpenPoster: (() => void) | null; // 포스터 원본 이미지가 있으면 창으로 연다
  onDetailChange: (detail: OpportunityDetail) => void;
  onShowAlternatives: () => void; // 지원 어려움: 아래 대체 공고(F-23)로 초점을 옮긴다
}

const FAILED = "준비 일정을 만들지 못했어요. 잠시 후 다시 눌러 주세요.";
// 화면이 기다리는 시간(60초)을 넘겼다. 실행은 계속 돌고 있어서 다시 열어 보면 된다
const STILL_RUNNING = "준비 일정을 아직 만들고 있어요. 잠시 뒤에 이 화면을 다시 열어 확인해 주세요.";

function deadlineCopy(detail: OpportunityDetail): string {
  const days = getDdayValue(detail.deadline_at, todayKst());
  if (days === null) return "상시 모집";
  if (days === 0) return "오늘 마감";
  if (days > 0) return `마감까지 ${days}일`;
  return "마감됨";
}

// 준비하지 못한 이유. 상시 공고의 목표일 오류는 그 항목 문구를, 기다리다 끊긴 경우는 화면 문구를 쓴다
function failureMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === "RUN_TIMEOUT") return STILL_RUNNING;
  return fieldErrors(error).target_date ?? errorMessage(error, FAILED);
}

export default function OpportunityPreparation({
  detail,
  calendarConnected,
  calendarResult,
  navigate,
  onOpenProfile,
  originalHref,
  onOpenPoster,
  onDetailChange,
  onShowAlternatives,
}: OpportunityPreparationProps) {
  const [steps, setSteps] = useState<ProcessStep[] | null>(null);
  const [result, setResult] = useState<PrepareResult | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [includeCalendar, setIncludeCalendar] = useState(true);
  const [running, setRunning] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [targetDate, setTargetDate] = useState(""); // 상시 공고의 준비 목표일
  const [message, setMessage] = useState<string | null>(null); // 준비하기를 하지 못한 이유
  // 다른 공고로 넘어가면 앞 공고의 진행·결과가 남지 않게 지운다(같은 컴포넌트를 다시 쓴다)
  useEffect(() => {
    setSteps(null);
    setResult(null);
    setMessage(null);
    setCompleted(false);
    setConfirmOpen(false);
    setTargetDate("");
  }, [detail.id]);

  const calendar = useCalendarEvent({
    detail,
    calendarConnected,
    calendarResult,
    onDetailChange,
    onMessage: setMessage,
  });
  const today = todayKst();
  const deadlineSoon = isDeadlineSoon(detail.deadline_at, today);
  const applicationPeriod = `${detail.apply_start_at ? formatKstDate(detail.apply_start_at) : "시작일 미정"} ~ ${
    detail.deadline_at ? formatKstDate(detail.deadline_at) : "상시"
  }`;

  // POST /opportunities/{id}/prepare → 실행 단계 → 결과. 지원 어려움(NOT_ELIGIBLE)이면 확인 창을 연다
  const startPreparation = async (force = false) => {
    setConfirmOpen(false);
    setCompleted(false);
    setResult(null);
    setMessage(null);
    setSteps([]);
    setRunning(true);
    try {
      const prepared = await prepareOpportunity(detail.id, targetDate || undefined, {
        force,
        onProgress: setSteps,
      });
      setResult(prepared);
      onDetailChange(await getOpportunity(detail.id));
    } catch (error) {
      setSteps(null);
      if (error instanceof ApiError && error.code === "NOT_ELIGIBLE") setConfirmOpen(true);
      else setMessage(failureMessage(error));
      // 마감이 지난 공고면 화면의 상태도 지금 것으로 바꾼다(다시 받지 못하면 문구만 남긴다)
      if (error instanceof ApiError && error.code === "DEADLINE_PASSED") {
        try {
          onDetailChange(await getOpportunity(detail.id));
        } catch {
          /* 상세를 다시 받지 못해도 위 문구는 보여 준다 */
        }
      }
    } finally {
      setRunning(false);
    }
  };

  // 완료: 체크했으면 마감일을 캘린더에 넣는다. 권한이 없으면 Google 화면으로 보내고(돌아오면 다시 누른다),
  // 캘린더만 실패해도 준비 일정은 이미 만들어져 있으니 그 사실을 알린다
  const finishPreparation = async () => {
    setFinishing(true);
    try {
      if (includeCalendar && detail.deadline_at) {
        await calendar.add(); // 권한이 없으면 Google 화면으로 떠난다(돌아오면 이어서 넣는다)
        if (!calendarConnected) return;
      }
      onDetailChange(await getOpportunity(detail.id));
      setCompleted(true);
    } catch (error) {
      setMessage(calendarFailure(error));
      try {
        onDetailChange(await getOpportunity(detail.id));
      } catch {
        /* 준비 일정은 이미 만들어졌다. 위 문구만 보여 준다 */
      }
    } finally {
      setFinishing(false);
    }
  };

  const action = (() => {
    if (result) {
      return <Badge tone="green">일정 생성 완료</Badge>;
    }
    if (detail.prep.prepared) {
      const progress =
        detail.prep.tasks_total > 0 ? (detail.prep.tasks_done / detail.prep.tasks_total) * 100 : 0;
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
            <Button onClick={() => startPreparation()} disabled={!running && !targetDate} busy={running}>
              준비 일정 만들기
            </Button>
          </div>
        );
      }
      return (
        <Button onClick={() => startPreparation()} busy={running}>
          {running ? "만드는 중" : "준비 일정 만들기"}
        </Button>
      );
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
        <Button onClick={onShowAlternatives}>대체 공고 보기</Button>
        <Button secondary onClick={() => setConfirmOpen(true)} busy={running}>
          그래도 준비하기
        </Button>
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
      <PreparationProgress
        steps={steps}
        result={result}
        calendarConnected={calendarConnected}
        hasDeadline={detail.deadline_at !== null}
        includeCalendar={includeCalendar}
        onIncludeCalendar={setIncludeCalendar}
        onConnectCalendar={() => void connectCalendar(calendar.here)}
        finishing={finishing}
        onFinish={finishPreparation}
      />
      {calendar.canRegister && !result && (
        <DeadlineCalendarRow
          registered={calendar.registered}
          busy={calendar.busy}
          onToggle={calendar.toggle}
        />
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
        <ModalDescription>
          지원 조건을 충족하지 못한 공고예요. 그래도 준비 일정을 만들까요?
        </ModalDescription>
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setConfirmOpen(false)}>취소</Button>
          <Button onClick={() => startPreparation(true)}>그래도 만들기</Button>
        </div>
      </Modal>
    </>
  );
}
