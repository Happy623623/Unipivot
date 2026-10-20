import { useState } from "react";
import { disconnectCalendar, disconnectLms, errorMessage, nowIso, reconnectCalendar } from "@/api/client";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import { formatRelativeTime } from "@/lib/format";
import type { LmsConnection, Me } from "@/types/api";

export type CalendarResult = "connected" | "error";

interface ConnectedServicesProps {
  me: Me;
  lms: LmsConnection; // GET /lms/connection
  calendarResult: CalendarResult | null; // Google 화면에서 돌아온 결과 (/settings?calendar=…)
  onMeChange: (me: Me) => void; // 목 모드는 연결 결과를 바로 돌려준다
}

const RESULT_NOTICE: Record<CalendarResult, { text: string; tone: string }> = {
  connected: { text: "Google Calendar를 연결했어요.", tone: "text-[#15803d]" },
  error: { text: "Google Calendar를 연결하지 못했어요. 연결하기를 다시 눌러 주세요.", tone: "text-[#c53030]" },
};

// 설정의 "연결된 서비스": Google Calendar 연결(증분 승인, API 4장)과 LearningX 연결 상태·해제
export default function ConnectedServices({ me, lms: initialLms, calendarResult, onMeChange }: ConnectedServicesProps) {
  const [connecting, setConnecting] = useState(false);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [lms, setLms] = useState(initialLms);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarDisconnectError, setCalendarDisconnectError] = useState<string | null>(null);
  // 돌아온 결과는 지금 상태와 맞을 때만 보여 준다(연결됐는데 "못 했어요"를 띄우지 않는다)
  const notice = calendarResult && (calendarResult === "connected") === me.calendar_connected
    ? RESULT_NOTICE[calendarResult]
    : null;

  // 실제 모드는 Google 화면으로 떠나므로 성공하면 이 함수가 끝나지 않고 "Google로 이동 중"이 남는다
  const connectCalendar = async () => {
    setConnecting(true);
    setCalendarError(null);
    try {
      onMeChange(await reconnectCalendar());
    } catch (caught) {
      setCalendarError(errorMessage(caught, "Google Calendar 연결을 시작하지 못했어요. 잠시 후 다시 시도해 주세요."));
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = async () => {
    setDisconnectError(null);
    try {
      setLms(await disconnectLms());
      setDisconnectOpen(false);
    } catch (caught) {
      setDisconnectError(errorMessage(caught, "연결을 해제하지 못했어요. 잠시 후 다시 눌러 주세요."));
    }
  };

  // Google 쪽 권한을 거두고 토큰을 지운다. 이미 넣은 일정은 캘린더에 남는다(F-06)
  const disconnectGoogle = async () => {
    setCalendarDisconnectError(null);
    try {
      onMeChange(await disconnectCalendar());
      setCalendarOpen(false);
    } catch (caught) {
      setCalendarDisconnectError(errorMessage(caught, "연결을 해제하지 못했어요. 잠시 후 다시 눌러 주세요."));
    }
  };

  return (
    <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
      <h2 className="text-[18px] font-semibold">연결된 서비스</h2>
      <div className="mt-4 flex flex-col divide-y divide-[#e5e7eb]">
        <div className="flex items-center justify-between gap-4 py-4">
          <div>
            <p className="text-[14px] font-semibold">Google Calendar</p>
            <p className="mt-1 text-[12px] text-[#667085]">
              {me.calendar_connected ? "연결됨" : "연결되지 않음. 연결하면 준비 일정을 캘린더에도 넣을 수 있어요."}
            </p>
            {(calendarError || notice) && (
              <p role="status" className={`mt-1 text-[12px] font-semibold ${calendarError ? "text-[#c53030]" : notice?.tone}`}>
                {calendarError ?? notice?.text}
              </p>
            )}
          </div>
          {me.calendar_connected ? (
            <Button secondary onClick={() => setCalendarOpen(true)}>연결 해제</Button>
          ) : (
            <Button secondary busy={connecting} onClick={connectCalendar}>
              {connecting ? "Google로 이동 중" : "연결하기"}
            </Button>
          )}
        </div>
        <div className="flex items-center justify-between gap-4 py-4">
          <div>
            <p className="text-[14px] font-semibold">LearningX</p>
            <p className="mt-1 text-[12px] text-[#667085]">
              {lms.status === "active"
                ? `토큰 끝 4자리 ${lms.token_last4} · 마지막 동기화 ${lms.last_synced_at ? formatRelativeTime(lms.last_synced_at, nowIso()) : "없음"}`
                : "연결되지 않음. 학업 화면에서 연결할 수 있어요."}
            </p>
          </div>
          {lms.status === "active" && (
            <Button secondary onClick={() => setDisconnectOpen(true)}>연결 해제</Button>
          )}
        </div>
      </div>
      <Modal open={calendarOpen} title="Google Calendar 연결 해제" onClose={() => setCalendarOpen(false)}>
        <p className="text-[14px] leading-6 text-[#344054]">
          연결을 해제하면 이 앱의 캘린더 권한을 거두고 저장한 토큰을 지워요. 이미 넣은 일정은 캘린더에 그대로 남고,
          새 일정은 다시 연결할 때까지 넣지 않아요.
        </p>
        {calendarDisconnectError && <p role="alert" className="mt-3 text-[13px] text-[#c53030]">{calendarDisconnectError}</p>}
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setCalendarOpen(false)}>취소</Button>
          <Button onClick={disconnectGoogle}>연결 해제</Button>
        </div>
      </Modal>
      <Modal open={disconnectOpen} title="LearningX 연결 해제" onClose={() => setDisconnectOpen(false)}>
        <p className="text-[14px] leading-6 text-[#344054]">
          연결을 해제하면 토큰을 바로 지워요. LearningX 설정에서도 토큰을 삭제해 주세요.
        </p>
        {disconnectError && <p role="alert" className="mt-3 text-[13px] text-[#c53030]">{disconnectError}</p>}
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setDisconnectOpen(false)}>취소</Button>
          <Button onClick={disconnect}>연결 해제</Button>
        </div>
      </Modal>
    </section>
  );
}
