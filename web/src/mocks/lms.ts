import type {
  Course,
  CourseDetail,
  LmsConnection,
  LmsUpdate,
  MaterialDetail,
} from "@/types/api";

export const lmsConnection: LmsConnection = {
  status: "active",
  token_last4: "4821",
  last_synced_at: "2026-10-05T09:30:00+09:00",
  last_error: null,
};

export const courses: Course[] = [
  { id: "linear-algebra", canvas_course_id: 2101, name: "선형대수", short_name: "선형대수", has_syllabus: true, portal_syllabus_url: "https://portal.example.edu/linear", open_assignments: 1, new_materials: 2, next_due: { kind: "syllabus", title: "Homework 4", due_at: "2026-10-13T23:59:00+09:00" } },
  { id: "analysis", canvas_course_id: 2102, name: "해석학", short_name: "해석학", has_syllabus: true, portal_syllabus_url: "https://portal.example.edu/analysis", open_assignments: 2, new_materials: 2, next_due: { kind: "assignment", title: "Homework 4", due_at: "2026-10-07T23:59:00+09:00" } },
  { id: "capstone", canvas_course_id: 2103, name: "DS창업캡스톤디자인1", short_name: "DS창업캡스톤디자인1", has_syllabus: true, portal_syllabus_url: "https://portal.example.edu/capstone", open_assignments: 1, new_materials: 2, next_due: { kind: "assignment", title: "창업아이템 정의", due_at: "2026-10-06T23:59:00+09:00" } },
  { id: "database", canvas_course_id: 2104, name: "데이터베이스", short_name: "데이터베이스", has_syllabus: false, portal_syllabus_url: "https://portal.example.edu/database", open_assignments: 2, new_materials: 2, next_due: { kind: "assignment", title: "SQL 실습", due_at: "2026-10-08T23:59:00+09:00" } },
];

function makeCourseDetail(course: Course, index: number): CourseDetail {
  const prefixes = ["기초 개념", "핵심 정리", "응용 문제"];
  return {
    course: {
      id: course.id,
      short_name: course.short_name,
      html_url: `https://lms.example.edu/courses/${course.canvas_course_id}`,
      has_syllabus: course.has_syllabus,
      portal_syllabus_url: course.portal_syllabus_url,
    },
    assignments: prefixes.map((title, assignmentIndex) => ({
      id: `${course.id}-a${assignmentIndex + 1}`,
      title: `${title} 과제`,
      due_at: `2026-10-${String(6 + index * 2 + assignmentIndex * 5).padStart(2, "0")}T23:59:00+09:00`,
      submission_state: assignmentIndex === 2 ? "submitted" : "unsubmitted",
      html_url: `https://lms.example.edu/${course.id}/assignments/${assignmentIndex + 1}`,
    })),
    module_items: [1, 2, 3, 4].map((week) => ({
      id: `${course.id}-m${week}`,
      module_name: `${week + 4}주차`,
      title: `${week + 4}주차 강의자료`,
      html_url: `https://lms.example.edu/${course.id}/modules/${week}`,
      is_new: week >= 3,
      uploaded_file_id: week === 4 ? `${course.id}-material` : null,
    })),
    announcements: [
      { id: `${course.id}-n1`, title: "다음 주 강의실 변경", summary: "다음 주 수업은 제2공학관 301호에서 진행해요.", category: "schedule_change", posted_at: "2026-10-05T08:00:00+09:00", opportunity_id: null },
      { id: `${course.id}-n2`, title: "보충 강의자료 등록", summary: "중간고사 대비 예제 자료를 추가했어요.", category: "material", posted_at: "2026-10-04T16:00:00+09:00", opportunity_id: null },
      { id: `${course.id}-n3`, title: "수업 연계 프로그램 안내", summary: "수강생이 참여할 수 있는 비교과 프로그램을 안내해요.", category: "opportunity", posted_at: "2026-10-03T11:00:00+09:00", opportunity_id: course.id === "database" ? "database-hackathon" : null },
    ],
    syllabus_items: [
      { id: `${course.id}-s1`, item_type: "midterm", title: "중간고사", starts_at: "2026-10-22T10:00:00+09:00", is_confirmed: true },
      { id: `${course.id}-s2`, item_type: "assignment", title: "Homework 4", starts_at: "2026-10-13T23:59:00+09:00", is_confirmed: true },
      { id: `${course.id}-s3`, item_type: "presentation", title: "팀 발표", starts_at: "2026-11-12T14:00:00+09:00", is_confirmed: false },
    ],
    materials: [{ file_id: `${course.id}-material`, original_name: `${course.short_name}_8주차.pdf`, status: "succeeded" }],
  };
}

export const courseDetails: Record<string, CourseDetail> = Object.fromEntries(
  courses.map((course, index) => [course.id, makeCourseDetail(course, index)]),
);

function makeMaterial(course: Course): MaterialDetail {
  const overLimit = course.id === "database";
  return {
    file_id: `${course.id}-material`,
    original_name: `${course.short_name}_8주차.pdf`,
    total_pages: overLimit ? 84 : 42,
    page_start: 1,
    page_end: 42,
    over_limit: overLimit,
    overall_summary: `${course.short_name} 8주차 핵심 개념과 예제를 정리한 자료예요.`,
    status: "succeeded",
    sections: [1, 2, 3, 4, 5].map((seq) => ({
      id: `${course.id}-section-${seq}`,
      seq,
      title: `${seq}부 핵심 개념`,
      page_start: (seq - 1) * 8 + 1,
      page_end: seq === 5 ? 42 : seq * 8,
      summary: `${seq}부의 정의와 주요 예제를 요약했어요.`,
      translation_status: seq === 1 ? "succeeded" : null,
      translation_url: seq === 1 ? `https://example.edu/materials/${course.id}/translation/1` : null,
    })),
  };
}

export const materials: Record<string, MaterialDetail> = Object.fromEntries(
  courses.map((course) => [`${course.id}-material`, makeMaterial(course)]),
);

export const lmsUpdates: LmsUpdate[] = [
  { type: "module_item", id: "analysis-m4", course: { id: "analysis", short_name: "해석학" }, module_name: "8주차", title: "Decision Trees", html_url: "https://lms.example.edu/analysis/modules/4", first_seen_at: "2026-10-05T09:20:00+09:00", uploaded_file_id: "analysis-material" },
  { type: "assignment", id: "capstone-a1", course: { id: "capstone", short_name: "DS창업캡스톤디자인1" }, title: "창업아이템 정의", due_at: "2026-10-06T23:59:00+09:00", submission_state: "unsubmitted" },
  { type: "announcement", id: "database-n1", course: { id: "database", short_name: "데이터베이스" }, title: "다음 주 강의실 변경", summary: "제2공학관 301호에서 수업해요.", posted_at: "2026-10-05T08:00:00+09:00", category: "schedule_change", attachment_count: 0, opportunity_id: null, planner_task_id: "task-db-notice" },
];
