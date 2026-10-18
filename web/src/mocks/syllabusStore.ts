import { ApiError } from "@/api/http";
import { getDevScenario } from "@/dev/scenarios";
import { getStoredMe } from "@/mocks/accountStore";
import { courseDetails } from "@/mocks/lms";
import { syncStoredSyllabusTask } from "@/mocks/store";
import type {
  CourseDetail,
  SyllabusConfirmItem,
  SyllabusConfirmResult,
  SyllabusExtractResult,
  SyllabusItemView,
} from "@/types/api";

// 목 모드의 계획서 추출·확정 (F-14). 메모리에만 있어 새로고침하면 초기화된다.
// 목데이터의 "데이터베이스"는 계획서가 없는 과목이라(has_syllabus false) 업로드 흐름을 그대로 돈다

// 뽑은 척할 일정. 주차만 적힌 계획서를 모델이 센 모양이다(시각이 없는 일정은 그날 09:00)
const EXTRACTED: Omit<SyllabusItemView, "id" | "is_confirmed" | "calendar_registered">[] = [
  { item_type: "midterm", title: "중간고사", starts_at: "2026-10-20T10:30:00+09:00" },
  { item_type: "presentation", title: "팀 프로젝트 중간 발표", starts_at: "2026-11-10T09:00:00+09:00" },
  { item_type: "final", title: "기말고사", starts_at: "2026-12-08T10:30:00+09:00" },
];

interface StoredSyllabus {
  courseId: string;
  items: SyllabusItemView[];
  calendar: Set<string>; // 캘린더에 넣은 일정
}

const stored = new Map<string, StoredSyllabus>(); // syllabus_id → 계획서

function syllabusIdOf(courseId: string): string {
  return `mock-syllabus-${courseId}`;
}

// POST /syllabi/extract 흉내. 이미 계획서가 있는 과목은 409이고, `replace`면 갈아 끼운다.
// 상태 미리보기의 "계획서 읽기 실패"는 실행이 실패한 것처럼 422를 준다
export function extractStoredSyllabus(
  courseId: string,
  replace: boolean,
):
  | { run_id: string; result: SyllabusExtractResult }
  | ApiError {
  if (getDevScenario() === "syllabus_failure") {
    return new ApiError(
      "SYLLABUS_READ_FAILED",
      "PDF에서 글자를 찾지 못했어요. 포털 계획서를 브라우저에서 PDF로 저장해 올려 주세요.",
      422,
    );
  }
  const id = syllabusIdOf(courseId);
  const already = stored.has(id) || courseDetails[courseId]?.course.has_syllabus;
  if (already && !replace) {
    return new ApiError(
      "SYLLABUS_EXISTS",
      "이 과목에는 이미 계획서가 있어요. 다시 올리면 기존 일정을 바꿔요.",
      409,
    );
  }
  const items: SyllabusItemView[] = EXTRACTED.map((item, index) => ({
    ...item,
    id: `${id}-${index + 1}`,
    is_confirmed: false,
    calendar_registered: false,
  }));
  stored.set(id, { courseId, items, calendar: new Set() });
  const course = courseDetails[courseId];
  return {
    run_id: `mock-run-${id}`,
    result: {
      kind: "syllabus_extract",
      syllabus_id: id,
      course_name: course?.course.short_name ?? null,
      items,
    },
  };
}

// POST /syllabi/{id}/confirm 흉내. 고른 것만 확정하고, 캘린더는 연결했을 때만 넣는다
export function confirmStoredSyllabus(
  syllabusId: string,
  asked: SyllabusConfirmItem[],
  registerCalendar: boolean,
): SyllabusConfirmResult | ApiError {
  // 상태 미리보기의 "캘린더 만료"를 고르면 getMe가 연결 안 됨으로 오고(mockClient), 화면은 체크를
  // 숨긴다. 그래도 확정 도중에 권한이 풀리는 길을 보려면 여기서도 같은 기준을 본다
  const calendarConnected =
    getStoredMe().calendar_connected && getDevScenario() !== "calendar_expired";
  const syllabus = stored.get(syllabusId);
  if (!syllabus) {
    return new ApiError("NOT_FOUND", "계획서를 찾을 수 없어요.", 404);
  }
  const sent = new Map(asked.map((item) => [item.id, item]));
  // 검사 순서도 서버와 같게 둔다 — 일정을 먼저 보고, 그다음 캘린더 연결을 본다
  if (asked.some((item) => !syllabus.items.some((row) => row.id === item.id))) {
    return new ApiError(
      "VALIDATION_FAILED",
      "그 계획서에 없는 일정이에요. 화면을 새로 고치고 다시 해 주세요.",
      422,
    );
  }
  if (sent.size !== asked.length) {
    return new ApiError(
      "VALIDATION_FAILED",
      "같은 일정이 두 번 들어 있어요. 화면을 새로 고치고 다시 해 주세요.",
      422,
    );
  }
  const undated = asked.filter(
    (item) =>
      item.selected &&
      !(item.starts_at ?? syllabus.items.find((row) => row.id === item.id)?.starts_at),
  );
  if (undated.length > 0) {
    return new ApiError(
      "VALIDATION_FAILED",
      "날짜가 없는 일정은 고를 수 없어요. 날짜를 적거나 선택을 풀어 주세요.",
      422,
    );
  }
  if (asked.some((item) => !item.title.trim())) {
    return new ApiError("VALIDATION_FAILED", "입력값을 확인해 주세요.", 422, {
      fields: { "items.0.title": "일정 이름을 적어 주세요." },
    });
  }
  if (registerCalendar && !calendarConnected) {
    return new ApiError("CALENDAR_NOT_CONNECTED", "Google 캘린더를 연결해 주세요.", 409, {
      reason: "not_connected",
    });
  }
  let confirmed = 0;
  let tasks = 0;
  let events = 0;
  syllabus.items = syllabus.items.map((row) => {
    const fixed = sent.get(row.id);
    if (!fixed) return row;
    const starts_at = fixed.starts_at ?? row.starts_at;
    const course = courseDetails[syllabus.courseId]?.course.short_name ?? null;
    // 플래너에도 넣는다(실제 서버가 하는 일). 날짜는 KST 날짜다
    const made = syncStoredSyllabusTask(
      row.id,
      fixed.title,
      (starts_at ?? "").slice(0, 10),
      course,
      fixed.selected,
    );
    if (fixed.selected) {
      confirmed += 1;
      if (made) tasks += 1;
      if (registerCalendar && starts_at && !syllabus.calendar.has(row.id)) {
        syllabus.calendar.add(row.id);
        events += 1;
      }
    }
    return {
      ...row,
      title: fixed.title,
      starts_at,
      is_confirmed: fixed.selected,
      calendar_registered: syllabus.calendar.has(row.id),
    };
  });
  return {
    confirmed,
    planner_tasks_created: tasks,
    calendar_events_created: events,
    calendar_events_moved: 0,
  };
}

// 과목 상세에 계획서 일정을 끼워 준다(GET /lms/courses/{id} 흉내)
export function withStoredSyllabus(course: CourseDetail): CourseDetail {
  const syllabus = stored.get(syllabusIdOf(course.course.id));
  if (!syllabus) return course;
  return {
    ...course,
    course: { ...course.course, has_syllabus: true, syllabus_id: syllabusIdOf(course.course.id) },
    // 캘린더에 넣은 일정은 다시 열어도 "넣었어요"로 보인다(서버의 calendar_registered 흉내)
    syllabus_items: syllabus.items.map((item) => ({
      ...item,
      calendar_registered: syllabus.calendar.has(item.id),
    })),
  };
}

export function registerStoredSyllabusEvent(itemId: string): void {
  for (const syllabus of stored.values()) {
    if (syllabus.items.some((item) => item.id === itemId)) syllabus.calendar.add(itemId);
  }
}
