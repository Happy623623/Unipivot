import { useEffect, useRef, useState } from "react";
import {
  getCourses,
  getLmsConnection,
  getLmsUpdates,
  nowIso,
  syncLmsNow,
  todayKst,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Header from "@/components/Header";
import LmsConnectModal from "@/components/LmsConnectModal";
import Skeleton from "@/components/Skeleton";
import {
  formatDday,
  formatKstShortDate,
  formatRelativeTime,
  isDeadlineSoon,
} from "@/lib/format";
import useAsyncData from "@/lib/useAsyncData";
import type { LmsConnection, LmsUpdate, LmsUpdateGroups } from "@/types/api";
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

// 줄마다 무엇(과목·주차), 제목, 날짜를 보인다. 과제는 마감일과 D-day, 새 자료는 들어온 때, 공지는 올린 때다
function updateLine(update: LmsUpdate): { label: string; note: string | null; when: string; urgent: boolean } {
  const course = update.course.short_name;
  if (update.type === "assignment") {
    const due = update.due_at;
    return {
      label: course,
      note: null,
      when: due ? `${formatKstShortDate(due)} 마감 · ${formatDday(due, todayKst())}` : "마감 없음",
      urgent: isDeadlineSoon(due, todayKst()),
    };
  }
  if (update.type === "module_item") {
    return {
      label: update.module_name ? `${course} · ${update.module_name}` : course,
      note: null,
      when: formatRelativeTime(update.first_seen_at, nowIso()),
      urgent: false,
    };
  }
  return { label: course, note: update.summary, when: formatRelativeTime(update.posted_at, nowIso()), urgent: false };
}

function UpdateGroup({
  title,
  updates,
  navigate,
}: {
  title: string;
  updates: LmsUpdate[];
  navigate: (route: Route) => void;
}) {
  if (updates.length === 0) return null;
  return (
    <div>
      <h3 className="text-[13px] font-semibold text-[#344054]">
        {title} <span className="text-[#667085]">{updates.length}</span>
      </h3>
      <ul className="mt-1.5 flex flex-col">
        {updates.map((update) => {
          const line = updateLine(update);
          return (
            <li key={`${update.type}-${update.id}`}>
              <button
                type="button"
                onClick={() => navigate(updateRoute(update))}
                className="flex w-full items-start justify-between gap-3 rounded-[10px] px-2 py-1.5 text-left hover:bg-[#f7f8fa]"
              >
                <span className="min-w-0">
                  <span className="block text-[12px] text-[#667085]">{line.label}</span>
                  <b className="block truncate text-[14px] font-semibold">{update.title}</b>
                  {line.note && <span className="block truncate text-[12px] text-[#667085]">{line.note}</span>}
                </span>
                <span className={`mt-0.5 shrink-0 text-[12px] font-semibold ${line.urgent ? "text-[#c53030]" : "text-[#667085]"}`}>
                  {line.when}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// 새로 들어온 학업 정보(피드백 2②): 과제 · 새 자료 · 공지로 나눈다. 빈 묶음은 숨긴다
function UpdateGroups({ groups, navigate }: { groups: LmsUpdateGroups; navigate: (route: Route) => void }) {
  const total = groups.assignments.length + groups.materials.length + groups.announcements.length;
  return (
    <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
      <h2 className="text-[18px] font-semibold">새로 들어온 학업 정보</h2>
      {total === 0 ? (
        <p className="mt-3 text-[13px] text-[#667085]">
          LearningX를 연결한 뒤 최근 2주 동안 새로 올라온 과제·자료·공지가 없어요. 지난 자료는 과목을 눌러 보세요.
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-4">
          <UpdateGroup title="과제" updates={groups.assignments} navigate={navigate} />
          <UpdateGroup title="새 자료" updates={groups.materials} navigate={navigate} />
          <UpdateGroup title="공지" updates={groups.announcements} navigate={navigate} />
        </div>
      )}
    </section>
  );
}

// 내 파일과 나눠 말한다(피드백 2④ — 두 곳의 구분이 안 보였다)
const SUBTITLE = "LearningX의 과제·주차 자료·공지를 과목별로 보여 줘요. 강의자료 PDF를 올리면 요약하고, 받은 파일은 내 파일에 모여요.";

export default function Academics({ navigate }: AcademicsProps) {
  const [syncedAt, setSyncedAt] = useState(0); // 동기화가 끝나면 올려서 목록을 다시 받는다
  // 다시 받는 동안 지난 목록을 둔다. 뼈대로 바꾸면 연결 창이 내려가 창 안 완료 글·닫은 뒤의 안내가 사라진다
  const request = useAsyncData(
    () => Promise.all([getLmsConnection(), getCourses(), getLmsUpdates()]),
    [syncedAt],
    { keep: true },
  );
  const [connectionOverride, setConnectionOverride] =
    useState<LmsConnection | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  // 연결하면 서버가 이미 과목을 받아 뒀다(첫 동기화도 끝났다). 목록을 다시 받아야 화면이 채워진다
  const connected = (next: LmsConnection) => {
    setConnectionOverride(next);
    setSyncedAt(Date.now());
  };
  const status = (connectionOverride ?? request.data?.[0])?.status ?? null;

  // 화면을 열면 LMS를 한 번 받아 온다(명세 9장). 마지막 동기화가 5분 안이면 서버가 건너뛴다.
  // 받는 동안에도 저장해 둔 과제·자료를 그대로 보여 주고, 새로 받으면 그때 다시 그린다.
  // 연결을 끊었다 다시 이어 status가 바뀌어도 화면을 열어 둔 동안 한 번만 부르게 막아 둔다
  const asked = useRef(false);
  useEffect(() => {
    if (status !== "active" || asked.current) return;
    asked.current = true;
    let alive = true;
    syncLmsNow().then((fresh) => {
      if (alive && fresh) setSyncedAt(Date.now());
    });
    return () => {
      alive = false;
    };
  }, [status]);

  if (request.loading && !request.data) return <AcademicsSkeleton />;
  if (!request.data) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "학업 정보를 불러오지 못했어요."}
      </p>
    );
  }
  // 다시 받지 못했으면 지난 목록을 두고 위에 알린다(연결 창·안내가 사라지지 않게)
  const reloadFailed = request.error && (
    <p role="status" className="rounded-[14px] bg-[#fef2f2] p-4 text-[13px] text-[#c53030]">
      목록을 새로 받지 못해 지난 목록을 보여 주고 있어요. 잠시 후 이 화면을 다시 열어 주세요.
    </p>
  );

  const [, courses, updates] = request.data;
  const connection = connectionOverride ?? request.data[0];

  if (connection.status === "disconnected") {
    return (
      <>
        <Header title="학업" subtitle={SUBTITLE} />
        {reloadFailed}
        <section className="flex min-h-[480px] flex-col items-center justify-center rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center">
          <Badge tone="yellow">LearningX 미연결</Badge>
          <h2 className="mt-4 text-[24px] font-bold">LearningX를 연결해 주세요</h2>
          <p className="mt-2 text-[14px] text-[#667085]">
            연결하면 과제 마감일과 새 강의자료를 한곳에서 확인할 수 있어요.
          </p>
          <div className="mt-6"><Button onClick={() => setConnectOpen(true)}>LearningX 연결하기</Button></div>
        </section>
        {/* 연결 창은 연결 전·후 트리에서 **같은 자리(세 번째)**에 둔다. 자리가 바뀌면 React가 창을
            새로 만들어 "연결했어요" 대신 1단계가 다시 뜬다 */}
        <LmsConnectModal
          key="lms-connect"
          open={connectOpen}
          onClose={() => setConnectOpen(false)}
          onConnected={connected}
        />
      </>
    );
  }

  return (
    <>
      <Header title="학업" subtitle={SUBTITLE} />
      {reloadFailed}
      {connection.status === "error" ? (
        <section className="flex items-center justify-between gap-4 rounded-[14px] bg-[#fef2f2] p-[18px]">
          <p className="text-[13px] font-semibold text-[#c53030]">
            {connection.last_error ?? "LearningX 연결이 끊겼어요. 토큰이 만료됐거나 삭제됐어요"}
          </p>
          <Button secondary onClick={() => setConnectOpen(true)}>다시 연결</Button>
        </section>
      ) : (
        <section className="flex items-center gap-3 rounded-[14px] bg-[#eef2ff] p-[18px]">
          <Badge tone="green">LearningX 연결됨</Badge>
          <p className="text-[13px] font-medium text-[#344054]">
            마지막 동기화: {connection.last_synced_at ? formatRelativeTime(connection.last_synced_at, nowIso()) : "아직 없음"} · 토큰 끝 4자리 {connection.token_last4}
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
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge>과제 {course.open_assignments}</Badge>
              <Badge tone="yellow">새 자료 {course.new_materials}</Badge>
              {(course.lectures_todo ?? 0) > 0 && <Badge tone="red">안 들은 강의 {course.lectures_todo}</Badge>}
            </div>
            <p className="mt-3 text-[12px] font-medium text-[#667085]">다음 일정</p>
            <p className="mt-2 text-[14px] font-semibold">
              {course.next_due
                ? `${course.next_due.title} · ${formatDday(course.next_due.due_at, todayKst())}`
                : "예정된 일정 없음"}
            </p>
            <span className="mt-3 block text-[12px] font-semibold text-[#4f6ef7]">
              과제 · 자료 · 공지 · 계획서 보기&nbsp; →
            </span>
          </button>
        ))}
      </section>
      {courses.length === 0 && (
        <section className="rounded-2xl border border-[#e5e7eb] bg-white p-8 text-center">
          {/* 다시 받는 동안에는 지난(빈) 목록을 두므로 받는 중이라고 쓴다(연결한 바로 뒤에도 그렇다) */}
          <p className="text-[14px] font-semibold">{request.loading ? "과목을 받아오고 있어요" : "아직 받아온 과목이 없어요"}</p>
          <p className="mt-2 text-[13px] text-[#667085]">
            이번 학기 수강 과목이 LearningX에 올라와 있는지 확인하고 다시 받아와 주세요.
          </p>
          <div className="mt-5">
            <Button secondary onClick={() => setSyncedAt(Date.now())} busy={request.loading}>다시 받아오기</Button>
          </div>
        </section>
      )}
      <UpdateGroups groups={updates} navigate={navigate} />
      <LmsConnectModal
        key="lms-connect"
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        onConnected={connected}
      />
    </>
  );
}
