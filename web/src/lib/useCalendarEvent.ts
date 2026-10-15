import { useEffect, useState } from "react";
import {
  ApiError,
  connectCalendar,
  getOpportunity,
  registerCalendarEvent,
  removeCalendarEvent,
} from "@/api/client";
import { calendarFailure } from "@/components/DeadlineCalendarRow";
import { routeToHref } from "@/lib/routes";
import type { OpportunityDetail } from "@/types/api";

interface Options {
  detail: OpportunityDetail;
  calendarConnected: boolean;
  calendarResult: "connected" | "error" | null;
  onDetailChange: (detail: OpportunityDetail) => void;
  onMessage: (message: string | null) => void;
}

/**
 * 마감일 캘린더 등록(F-32)의 상태와 동작.
 *
 * - 권한이 없으면 Google 증분 승인으로 보낸다. 돌아오면(?calendar=connected) 하려던 등록을 이어서 한다
 * - 넣는 중에 권한이 만료됐다고 하면(CALENDAR_NOT_CONNECTED) 다시 연결 화면으로 보낸다
 */
export default function useCalendarEvent({
  detail,
  calendarConnected,
  calendarResult,
  onDetailChange,
  onMessage,
}: Options) {
  const [busy, setBusy] = useState(false);
  const here = routeToHref({ name: "opportunity", id: detail.id }); // 연결 뒤 돌아올 곳
  const registered = detail.prep.calendar_events.length > 0;
  const canRegister = detail.prep.prepared && detail.deadline_at !== null;

  const add = async () => {
    if (!calendarConnected) return connectCalendar(here);
    await registerCalendarEvent(detail.id);
    onDetailChange(await getOpportunity(detail.id));
  };

  // Google 연결에서 돌아왔다. 연결됐으면 이어서 넣고, 실패했으면 까닭을 알린다
  useEffect(() => {
    if (calendarResult === "error") {
      onMessage("Google 캘린더를 연결하지 못했어요. 다시 눌러 주세요.");
      return;
    }
    if (calendarResult !== "connected" || !calendarConnected) return;
    if (!canRegister || registered) return;
    let alive = true;
    setBusy(true);
    registerCalendarEvent(detail.id)
      .then(() => getOpportunity(detail.id))
      .then((fresh) => alive && onDetailChange(fresh))
      .catch((error) => alive && onMessage(calendarFailure(error)))
      .finally(() => alive && setBusy(false));
    return () => {
      alive = false;
    };
    // 돌아온 직후 한 번만 한다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calendarResult, calendarConnected]);

  const toggle = async () => {
    setBusy(true);
    onMessage(null);
    try {
      const event = detail.prep.calendar_events[0];
      if (event) {
        await removeCalendarEvent(event.id);
        onDetailChange(await getOpportunity(detail.id));
      } else {
        await add();
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "CALENDAR_NOT_CONNECTED") {
        await connectCalendar(here); // 서버는 만료라고 본다. 권한을 다시 받는다
        return;
      }
      onMessage(calendarFailure(error));
    } finally {
      setBusy(false);
    }
  };

  return { busy, registered, canRegister, here, add, toggle };
}
