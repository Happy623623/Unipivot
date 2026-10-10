import { useState } from "react";
import {
  getCourses,
  getLmsConnection,
  getLmsUpdates,
  MOCK_NOW,
  MOCK_TODAY,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Header from "@/components/Header";
import LmsConnectModal from "@/components/LmsConnectModal";
import Skeleton from "@/components/Skeleton";
import { formatDday, formatRelativeTime, isDeadlineSoon } from "@/lib/format";
import useAsyncData from "@/lib/useAsyncData";
import type { LmsConnection, LmsUpdate } from "@/types/api";
import type { Route } from "@/types/route";

interface AcademicsProps {
  navigate: (route: Route) => void;
}

function AcademicsSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[430px]" />
      <Skeleton className="h-[62px] w-full rounded-[14px]" />
      <div className="grid grid-cols-3 gap-4">
        <Skeleton className="h-[230px] rounded-2xl" />
        <Skeleton className="h-[230px] rounded-2xl" />
        <Skeleton className="h-[230px] rounded-2xl" />
      </div>
    </>
  );
}

function updateRoute(update: LmsUpdate): Route {
  if (update.type === "module_item") {
    return { name: "course", id: update.course.id, tab: "materials" };
  }
  if (update.type === "announcement") {
    return { name: "course", id: update.course.id, tab: "announcements" };
  }
  return { name: "course", id: update.course.id, tab: "assignments" };
}

function UpdateItem({
  update,
  navigate,
}: {
  update: LmsUpdate;
  navigate: (route: Route) => void;
}) {
  const heading =
    update.type === "module_item"
      ? `${update.course.short_name} ${update.module_name} 자료`
      : update.type === "announcement"
        ? `${update.course.short_name} 공지`
        : `${update.course.short_name} ${
            isDeadlineSoon(update.due_at, MOCK_TODAY) ? "과제 마감 임박" : "새 과제"
          }`;
  const note =
    update.type === "module_item"
      ? update.title
      : update.type === "announcement"
        ? update.summary
        : `${update.title} · ${formatDday(update.due_at, MOCK_TODAY)}`;
  const color =
    update.type === "assignment"
      ? "text-[#c53030]"
      : update.type === "announcement"
        ? "text-[#b7791f]"
        : "text-[#4f6ef7]";

  return (
    <button
      type="button"
      onClick={() => navigate(updateRoute(update))}
      className="flex w-full gap-3 rounded-[10px] p-1 text-left hover:bg-[#f7f8fa]"
    >
      <span className={`mt-1 text-[12px] ${color}`}>●</span>
      <span className="min-w-0">
        <b className="block text-[14px] font-semibold">{heading}</b>
        <span className="mt-0.5 block truncate text-[12px] text-[#667085]">{note}</span>
      </span>
    </button>
  );
}

export default function Academics({ navigate }: AcademicsProps) {
  const request = useAsyncData(
    () => Promise.all([getLmsConnection(), getCourses(), getLmsUpdates()]),
    [],
  );
  const [connectionOverride, setConnectionOverride] =
    useState<LmsConnection | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);

  if (request.loading) return <AcademicsSkeleton />;
  if (request.error || !request.data) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "학업 정보를 불러오지 못했어요."}
      </p>
    );
  }

  const [, courses, updates] = request.data;
  const connection = connectionOverride ?? request.data[0];

  if (connection.status === "disconnected") {
    return (
      <>
        <Header title="학업" subtitle="LMS 과제와 새 자료를 확인하고 강의자료를 요약할 수 있어요." />
        <section className="flex min-h-[480px] flex-col items-center justify-center rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center">
          <Badge tone="yellow">LearningX 미연결</Badge>
          <h2 className="mt-4 text-[24px] font-bold">LearningX를 연결해 주세요</h2>
          <p className="mt-2 text-[14px] text-[#667085]">
            연결하면 과제 마감일과 새 강의자료를 한곳에서 확인할 수 있어요.
          </p>
          <div className="mt-6"><Button onClick={() => setConnectOpen(true)}>LearningX 연결하기</Button></div>
        </section>
        <LmsConnectModal
          open={connectOpen}
          onClose={() => setConnectOpen(false)}
          onConnected={setConnectionOverride}
        />
      </>
    );
  }

  return (
    <>
      <Header title="학업" subtitle="LMS 과제와 새 자료를 확인하고 강의자료를 요약할 수 있어요." />
      {connection.status === "error" ? (
        <section className="flex items-center justify-between gap-4 rounded-[14px] bg-[#fef2f2] p-[18px]">
          <p className="text-[13px] font-semibold text-[#c53030]">
            LearningX 연결이 끊겼어요. 토큰이 만료됐거나 삭제됐어요
          </p>
          <Button secondary onClick={() => setConnectOpen(true)}>다시 연결</Button>
        </section>
      ) : (
        <section className="flex items-center gap-3 rounded-[14px] bg-[#eef2ff] p-[18px]">
          <Badge tone="green">LearningX 연결됨</Badge>
          <p className="text-[13px] font-medium text-[#344054]">
            마지막 동기화: {connection.last_synced_at ? formatRelativeTime(connection.last_synced_at, MOCK_NOW) : "아직 없음"} · 토큰 끝 4자리 {connection.token_last4}
          </p>
        </section>
      )}
      <section className="grid grid-cols-4 gap-4 max-[1100px]:grid-cols-2 max-[760px]:grid-cols-1">
        {courses.map((course) => (
          <button
            type="button"
            key={course.id}
            onClick={() => navigate({ name: "course", id: course.id })}
            className="min-h-[230px] rounded-2xl border border-[#e5e7eb] bg-white p-[18px] text-left transition hover:-translate-y-0.5 hover:border-[#cfd7ff]"
          >
            <h2 className="text-[17px] font-semibold">{course.name}</h2>
            <div className="mt-3 flex gap-2">
              <Badge>과제 {course.open_assignments}</Badge>
              <Badge tone="yellow">새 자료 {course.new_materials}</Badge>
            </div>
            <p className="mt-3 text-[12px] font-medium text-[#667085]">다음 일정</p>
            <p className="mt-2 text-[14px] font-semibold">
              {course.next_due
                ? `${course.next_due.title} · ${formatDday(course.next_due.due_at, MOCK_TODAY)}`
                : "예정된 일정 없음"}
            </p>
            <span className="mt-3 block text-[12px] font-semibold text-[#4f6ef7]">
              과제 · 자료 · 공지 · 계획서 보기&nbsp; →
            </span>
          </button>
        ))}
      </section>
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <h2 className="text-[18px] font-semibold">새로 들어온 학업 정보</h2>
        <div className="mt-3 flex flex-col gap-3">
          {updates.map((update) => (
            <UpdateItem
              key={`${update.type}-${update.id}`}
              update={update}
              navigate={navigate}
            />
          ))}
        </div>
      </section>
      <LmsConnectModal
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        onConnected={setConnectionOverride}
      />
    </>
  );
}
