import { useEffect, useState } from "react";
import {
  addManualPlannerTask,
  deleteManualPlannerTask,
  downloadPlannerIcs,
  errorMessage,
  getMe,
  getPlanner,
  movePlannerTask,
  todayKst,
  setPlannerTaskDone,
  updateManualPlannerTask,
} from "@/api/client";
import Button from "@/components/Button";
import Header from "@/components/Header";
import PlannerCalendar from "@/components/PlannerCalendar";
import PlannerDayPanel from "@/components/PlannerDayPanel";
import Skeleton from "@/components/Skeleton";
import Toast from "@/components/Toast";
import useAsyncData from "@/lib/useAsyncData";
import useToast from "@/lib/useToast";
import type { PlannerResponse, PlannerTask } from "@/types/api";
import type { Route } from "@/types/route";

// 달력은 그 달 앞뒤의 며칠까지 같이 그린다(6주 42칸). 그 칸의 할 일·마감도 보이도록 넉넉히 받는다
const GRID_PAD_DAYS = 7;

function monthRange(year: number, month: number) {
  const first = new Date(Date.UTC(year, month - 1, 1));
  const last = new Date(Date.UTC(year, month, 0));
  const shift = (base: Date, days: number) =>
    new Date(base.getTime() + days * 86_400_000).toISOString().slice(0, 10);
  return { from: shift(first, -GRID_PAD_DAYS), to: shift(last, GRID_PAD_DAYS) };
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

export default function Planner({ navigate }: { navigate: (route: Route) => void }) {
  const [view, setView] = useState(() => ({
    year: Number(todayKst().slice(0, 4)),
    month: Number(todayKst().slice(5, 7)),
  }));
  const [selectedDate, setSelectedDate] = useState(todayKst);
  const [plannerOverride, setPlannerOverride] =
    useState<PlannerResponse | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [toast, showToast] = useToast();
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
  const calendarConnected = me.calendar_connected;
  const selectedTasks = planner.items.filter(
    (task) => task.due_date === selectedDate,
  );
  const selectedMarkers = planner.markers.filter(
    (marker) => marker.date === selectedDate,
  );

  const refresh = async () => {
    setPlannerOverride(await getPlanner(range.from, range.to));
  };

  // 저장하고 목록을 다시 받는다. 실패하면 화면은 그대로 두고 안내를 띄운 뒤 오류를 다시 던진다
  // (일정 추가·수정 창이 저장된 것처럼 닫히지 않게 한다)
  const save = async (work: () => Promise<unknown>, fallback: string) => {
    try {
      await work();
    } catch (error) {
      showToast(errorMessage(error, fallback));
      throw error;
    }
    await refresh();
  };

  const toggleTask = (task: PlannerTask) =>
    save(
      () => setPlannerTaskDone(task.id, !task.is_done),
      "할 일을 체크하지 못했어요. 잠시 후 다시 눌러 주세요.",
    ).catch(() => {});

  // Google 캘린더를 쓰지 않는 학생용(F-34). 오늘부터 1년 안의 마감·일정을 .ics 파일 하나로 받는다
  const downloadIcs = async () => {
    setDownloading(true);
    try {
      const saved = await downloadPlannerIcs();
      showToast(
        saved
          ? ".ics 파일을 내려받았어요. 캘린더 앱에서 열면 일정이 들어가요."
          : "내려받을 일정이 없어요. 준비한 공고나 LMS 과제가 생기면 받을 수 있어요.",
      );
    } catch (error) {
      showToast(errorMessage(error, "파일을 내려받지 못했어요. 잠시 후 다시 눌러 주세요."));
    } finally {
      setDownloading(false);
    }
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
            await save(
              () => addManualPlannerTask(title, date),
              "일정을 추가하지 못했어요. 잠시 후 다시 눌러 주세요.",
            );
            setSelectedDate(date); // 저장이 된 뒤에 그 날을 연다
          }}
          onEdit={async (task, title, date) => {
            await save(
              () =>
                task.source === "manual"
                  ? updateManualPlannerTask(task.id, title, date)
                  : movePlannerTask(task.id, date), // 준비 할 일은 날짜만 옮긴다
              "일정을 바꾸지 못했어요. 잠시 후 다시 눌러 주세요.",
            );
            setSelectedDate(date);
          }}
          onDelete={(id) =>
            save(
              () => deleteManualPlannerTask(id),
              "일정을 지우지 못했어요. 잠시 후 다시 눌러 주세요.",
            ).catch(() => {})
          }
        />
      </section>
      {/* 캘린더 연결은 설정 한 곳에서 한다(Google 화면을 거쳐 설정으로 돌아온다) */}
      <section className="flex items-center justify-between gap-4 rounded-[14px] border border-[#e5e7eb] bg-white p-[18px]">
        <div>
          <p className="text-[14px] font-semibold">
            <b className="mr-3 text-[#4f6ef7]">G</b>
            {calendarConnected ? "Google Calendar 연결됨" : "Google Calendar 연결 안 됨"}
          </p>
          <p className="ml-7 mt-1 text-[12px] text-[#667085]">
            {calendarConnected
              ? "준비 중인 공고 마감일과 LMS 과제 마감일을 Google Calendar에 등록해요."
              : "설정에서 연결하면 준비 일정과 마감일을 Google Calendar에 넣을 수 있어요."}
          </p>
        </div>
        {!calendarConnected && (
          <Button secondary onClick={() => navigate({ name: "settings" })}>
            설정에서 연결
          </Button>
        )}
      </section>
      {/* Google 캘린더를 쓰지 않는 학생은 파일로 받아 기본 캘린더 앱에 넣는다(F-34) */}
      <section className="flex items-center justify-between gap-4 rounded-[14px] border border-[#e5e7eb] bg-white p-[18px]">
        <div>
          <p className="text-[14px] font-semibold">.ics 파일로 내려받기</p>
          <p className="mt-1 text-[12px] text-[#667085]">
            Google 캘린더를 쓰지 않으면 다가오는 마감일과 수업 일정을 파일로 받아 iPhone·삼성·Outlook 캘린더에 넣을 수 있어요.
          </p>
        </div>
        <Button secondary onClick={downloadIcs} disabled={downloading}>
          {downloading ? "파일 만드는 중…" : ".ics 내려받기"}
        </Button>
      </section>
      <Toast toast={toast} />
    </>
  );
}
