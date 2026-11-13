import { useState } from "react";
import { nowIso } from "@/api/client";
import Badge from "@/components/Badge";
import { formatKstShortDate, formatRelativeTime, getKstTimeKey } from "@/lib/format";
import type { CourseLecture, LectureKind } from "@/types/api";
import type { Tone } from "@/types/route";

const NO_WEEK = "주차 미정";
const kindLabel: Record<LectureKind, string> = {
  video: "녹화 강의",
  live: "실시간 수업",
  material: "학습자료",
};

type View = "open" | "all";

// 아직 들을 수 있는(출석·지각 인정 기간 안) 강의. 과목 목록의 "안 들은 강의" 수와 같은 기준이다(api lectures.OPEN)
export function isOpenLecture(lecture: CourseLecture): boolean {
  return lecture.status === "todo" || lecture.status === "late";
}

function statusBadge(lecture: CourseLecture): { label: string; tone: Tone } {
  const reading = lecture.kind === "material"; // 학습자료는 "듣는" 것이 아니라 "보는" 것이다
  switch (lecture.status) {
    case "done":
      return { label: lecture.attendance === "late" ? "다 들음 · 지각" : reading ? "다 봄" : "다 들음", tone: "green" };
    case "todo":
      return { label: reading ? "안 봄" : "안 들음", tone: "red" };
    case "late":
      return { label: "지각 인정 기간", tone: "yellow" };
    case "missed":
      return { label: lecture.attendance === "absent" ? "결석" : "출석 기간 지남", tone: "gray" };
    case "upcoming":
      return { label: "열리기 전", tone: "blue" };
    default:
      return { label: "확인 못 함", tone: "gray" };
  }
}

function when(value: string): string {
  return `${formatKstShortDate(value)} ${getKstTimeKey(value)}`;
}

function deadline(lecture: CourseLecture): string | null {
  if (lecture.status === "upcoming" && lecture.unlock_at) return `${when(lecture.unlock_at)}에 열려요`;
  if (lecture.status === "late" && lecture.late_at) return `지각 인정 ${when(lecture.late_at)}까지`;
  if (lecture.status === "done" || lecture.status === "missed" || lecture.status === "unknown") return null;
  return lecture.due_at ? `출석 인정 ${when(lecture.due_at)}까지` : "출석 마감 없음";
}

function minutes(seconds: number | null): string | null {
  return seconds ? `${Math.max(1, Math.round(seconds / 60))}분` : null;
}

// 먼저 들을 순서: 마감이 가까운 것부터(지각 인정 기간이면 지각 마감), 마감이 없으면 뒤로
function dueKey(lecture: CourseLecture): string {
  return (lecture.status === "late" ? lecture.late_at : lecture.due_at) ?? "9999";
}

interface CourseLecturesProps {
  lectures: CourseLecture[];
  checkedAt: string | null;
}

// 과목 상세의 강의 탭(11/24). LearningX 주차학습에서 읽은 내 수강 상태를 보여 준다. 서비스는 강의를 열지 않으므로
// 출석은 학생이 LMS에서 들어야 인정된다 — 줄마다 LMS로 가는 길만 둔다
export default function CourseLectures({ lectures, checkedAt }: CourseLecturesProps) {
  const open = lectures.filter(isOpenLecture);
  const done = lectures.filter((lecture) => lecture.status === "done").length;
  const [view, setView] = useState<View>(open.length > 0 ? "open" : "all");
  const weeks = lectures.reduce<[string, CourseLecture[]][]>((groups, lecture) => {
    const week = lecture.module_name || NO_WEEK;
    const last = groups[groups.length - 1];
    if (last && last[0] === week) last[1].push(lecture); // 주차 순으로 오므로 이어 붙인다
    else groups.push([week, [lecture]]);
    return groups;
  }, []);
  const sortedOpen = [...open].sort((a, b) => dueKey(a).localeCompare(dueKey(b)) || a.id.localeCompare(b.id));

  const row = (lecture: CourseLecture, showWeek: boolean) => {
    const badge = statusBadge(lecture);
    const meta = [
      showWeek ? lecture.module_name || NO_WEEK : null,
      kindLabel[lecture.kind],
      minutes(lecture.duration_seconds),
      deadline(lecture),
    ].filter(Boolean);
    return (
      <li key={lecture.id} className="flex items-start justify-between gap-4 rounded-[12px] bg-[#f7f8fa] p-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[14px] font-semibold">{lecture.title}</p>
            <Badge tone={badge.tone}>{badge.label}</Badge>
          </div>
          <p className="mt-1 text-[12px] text-[#667085]">{meta.join(" · ")}</p>
        </div>
        {lecture.html_url && (
          <a
            href={lecture.html_url}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 text-[12px] font-semibold text-[#4f6ef7]"
          >
            {lecture.kind === "material" ? "LMS에서 보기" : "LMS에서 듣기"}
            <span className="sr-only">: {lecture.title}(새 탭)</span>
          </a>
        )}
      </li>
    );
  };

  return (
    <div className="flex flex-col gap-5">
      <section className="rounded-[12px] border border-[#e5e7eb] p-4">
        <h3 className="text-[15px] font-semibold">
          주차학습 {lectures.length}개 중 {done}개를 마쳤어요
        </h3>
        <p className="mt-1 text-[13px] text-[#344054]">
          {open.length > 0
            ? `아직 안 들은 강의가 ${open.length}개 있어요. 출석 인정 기간이 지나기 전에 LMS에서 들어 주세요.`
            : "출석 인정 기간 안에 들어야 할 강의는 다 들었어요."}
        </p>
        <p className="mt-2 text-[11px] leading-5 text-[#667085]">
          {checkedAt ? `LearningX에서 ${formatRelativeTime(checkedAt, nowIso())} 확인했어요. ` : ""}
          UNIPIVOT은 강의를 열지 않고 수강 상태만 읽어요. 강의는 LMS에서 들어야 출석이 인정되고, 방금 들은 강의는 다음
          동기화 때 바뀌어요.
        </p>
      </section>
      <div className="flex gap-2" role="group" aria-label="강의 보기">
        {(
          [
            ["open", `안 들은 강의 ${open.length}`],
            ["all", `전체 ${lectures.length}`],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={view === id}
            onClick={() => setView(id)}
            className={`rounded-full px-3 py-1.5 text-[12px] font-semibold ${
              view === id ? "bg-[#eef2ff] text-[#4f6ef7]" : "bg-[#f2f4f7] text-[#475467]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {view === "open" ? (
        sortedOpen.length > 0 ? (
          <ul className="flex flex-col gap-2">{sortedOpen.map((lecture) => row(lecture, true))}</ul>
        ) : (
          <p className="rounded-[12px] bg-[#f7f8fa] p-4 text-[13px] text-[#667085]">지금 들어야 할 강의가 없어요.</p>
        )
      ) : (
        weeks.map(([week, items], index) => (
          // 같은 이름의 주차가 떨어져 있을 수 있어 순서를 키에 섞는다
          <section key={`${index}-${week}`}>
            <h3 className="text-[15px] font-semibold">{week}</h3>
            <ul className="mt-2 flex flex-col gap-2">{items.map((lecture) => row(lecture, false))}</ul>
          </section>
        ))
      )}
    </div>
  );
}
