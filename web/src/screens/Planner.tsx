import { useEffect, useState } from "react";
import {
  addManualPlannerTask,
  deleteManualPlannerTask,
  getMe,
  getPlanner,
  MOCK_TODAY,
  setPlannerTaskDone,
  updateManualPlannerTask,
} from "@/api/client";
import Button from "@/components/Button";
import Header from "@/components/Header";
import PlannerCalendar from "@/components/PlannerCalendar";
import PlannerDayPanel from "@/components/PlannerDayPanel";
import Skeleton from "@/components/Skeleton";
import useAsyncData from "@/lib/useAsyncData";
import type { PlannerResponse, PlannerTask } from "@/types/api";

function monthRange(year: number, month: number) {
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const prefix = `${year}-${String(month).padStart(2, "0")}`;
  return { from: `${prefix}-01`, to: `${prefix}-${String(lastDay).padStart(2, "0")}` };
}

function PlannerSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[390px]" />
      <div className="grid grid-cols-[1.77fr_1fr] gap-5">
        <Skeleton className="h-[650px] rounded-2xl" />
        <Skeleton className="h-[650px] rounded-2xl" />
      </div>
    </>
  );
}

export default function Planner() {
  const [view, setView] = useState({
    year: Number(MOCK_TODAY.slice(0, 4)),
    month: Number(MOCK_TODAY.slice(5, 7)),
  });
  const [selectedDate, setSelectedDate] = useState(MOCK_TODAY);
  const [plannerOverride, setPlannerOverride] =
    useState<PlannerResponse | null>(null);
  const [calendarOverride, setCalendarOverride] = useState<boolean | null>(null);
  const range = monthRange(view.year, view.month);
  const request = useAsyncData(
    () => Promise.all([getPlanner(range.from, range.to), getMe()]),
    [range.from, range.to],
  );

  useEffect(() => {
    setPlannerOverride(null);
  }, [range.from, range.to]);

  if (request.loading) return <PlannerSkeleton />;
  if (request.error || !request.data) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "일정을 불러오지 못했어요."}
      </p>
    );
  }

  const planner = plannerOverride ?? request.data[0];
  const me = request.data[1];
  const calendarConnected =
    calendarOverride ?? me.calendar_connected;
  const selectedTasks = planner.items.filter(
    (task) => task.due_date === selectedDate,
  );
  const selectedMarkers = planner.markers.filter(
    (marker) => marker.date === selectedDate,
  );

  const refresh = async () => {
    setPlannerOverride(await getPlanner(range.from, range.to));
  };
  const toggleTask = async (task: PlannerTask) => {
    await setPlannerTaskDone(task.id, !task.is_done);
    await refresh();
  };

  return (
    <>
      <Header
        title="플래너"
        subtitle="공고 준비, LMS 과제, 수업 일정을 한곳에서 관리해요."
      />
      <section className="grid grid-cols-[1.77fr_1fr] gap-5 max-[1000px]:grid-cols-1">
        <PlannerCalendar
          year={view.year}
          month={view.month}
          planner={planner}
          selectedDate={selectedDate}
          onSelectDate={setSelectedDate}
          onMonthChange={(year, month) => setView({ year, month })}
        />
        <PlannerDayPanel
          date={selectedDate}
          tasks={selectedTasks}
          markers={selectedMarkers}
          onToggle={toggleTask}
          onAdd={async (title, date) => {
            await addManualPlannerTask(title, date);
            setSelectedDate(date);
            await refresh();
          }}
          onEdit={async (id, title, date) => {
            await updateManualPlannerTask(id, title, date);
            setSelectedDate(date);
            await refresh();
          }}
          onDelete={async (id) => {
            await deleteManualPlannerTask(id);
            await refresh();
          }}
        />
      </section>
      <section
        className={`flex items-center justify-between gap-4 rounded-[14px] border p-[18px] ${
          calendarConnected
            ? "border-[#e5e7eb] bg-white"
            : "border-[#e5e7eb] bg-[#fef2f2]"
        }`}
      >
        <div>
          <p className="text-[14px] font-semibold">
            <b className="mr-3 text-[#4f6ef7]">G</b>
            {calendarConnected
              ? "Google Calendar 연결됨"
              : "Google Calendar 연결 만료"}
          </p>
          <p className="ml-7 mt-1 text-[12px] text-[#667085]">
            {calendarConnected
              ? "준비 중인 공고 마감일과 LMS 과제 마감일을 Google Calendar에 등록해요."
              : "다시 로그인해서 연결해 주세요"}
          </p>
        </div>
        {!calendarConnected && (
          <Button secondary onClick={() => setCalendarOverride(true)}>
            다시 연결
          </Button>
        )}
      </section>
    </>
  );
}
