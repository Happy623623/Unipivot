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
  {
    id: "linear-algebra",
    canvas_course_id: 2101,
    name: "선형대수",
    short_name: "선형대수",
    has_syllabus: true,
    portal_syllabus_url: "https://portal.example.edu/linear",
    open_assignments: 1,
    new_materials: 2,
    next_due: {
      kind: "syllabus_item",
      title: "Homework 4",
      due_at: "2026-10-13T23:59:00+09:00",
    },
  },
  {
    id: "analysis",
    canvas_course_id: 2102,
    name: "해석학",
    short_name: "해석학",
    has_syllabus: true,
    portal_syllabus_url: "https://portal.example.edu/analysis",
    open_assignments: 2,
    new_materials: 2,
    next_due: {
      kind: "assignment",
      title: "Homework 4",
      due_at: "2026-10-07T23:59:00+09:00",
    },
  },
  {
    id: "capstone",
    canvas_course_id: 2103,
    name: "DS창업캡스톤디자인1",
    short_name: "DS창업캡스톤디자인1",
    has_syllabus: true,
    portal_syllabus_url: "https://portal.example.edu/capstone",
    open_assignments: 1,
    new_materials: 2,
    next_due: {
      kind: "assignment",
      title: "창업아이템 정의",
      due_at: "2026-10-06T23:59:00+09:00",
    },
  },
  {
    id: "database",
    canvas_course_id: 2104,
    name: "데이터베이스",
    short_name: "데이터베이스",
    has_syllabus: false,
    portal_syllabus_url: "https://portal.example.edu/database",
    open_assignments: 2,
    new_materials: 2,
    next_due: {
      kind: "assignment",
      title: "SQL 실습",
      due_at: "2026-10-08T23:59:00+09:00",
    },
  },
];

function makeCourseDetail(course: Course, index: number): CourseDetail {
  const prefixes = ["기초 개념", "핵심 정리", "응용 문제"];
  return {
    course: {
      id: course.id,
      short_name: course.short_name,
      html_url: `https://lms.example.edu/courses/${course.canvas_course_id}`,
      has_syllabus: course.has_syllabus,
      syllabus_id: course.has_syllabus ? `mock-syllabus-${course.id}` : null,
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
      item_type: "ExternalTool",
      html_url: `https://lms.example.edu/${course.id}/modules/${week}`,
      is_new: week >= 3,
      uploaded_file_id: week === 4 ? `${course.id}-material` : null,
    })),
    announcements: [
      {
        id: `${course.id}-n1`,
        title: "다음 주 강의실 변경",
        summary: "다음 주 수업은 제2공학관 301호에서 진행해요.",
        category: "schedule_change",
        posted_at: "2026-10-05T08:00:00+09:00",
        opportunity_id: null,
        attachments: [],
      },
      {
        id: `${course.id}-n2`,
        title: "보충 강의자료 등록",
        summary: "중간고사 대비 예제 자료를 추가했어요.",
        category: "material",
        posted_at: "2026-10-04T16:00:00+09:00",
        opportunity_id: null,
        // 공지 첨부(F-54): 받은 것, 20MB가 넘어 받지 않은 것
        attachments: [
          { name: "중간고사 대비 예제.pdf", size_bytes: 1_843_200, status: "saved", file_id: `${course.id}-n2-file` },
          { name: "예제 풀이 영상.mp4", size_bytes: 48_234_496, status: "too_large", file_id: null },
        ],
      },
      {
        id: `${course.id}-n3`,
        title: "수업 연계 프로그램 안내",
        summary: "수강생이 참여할 수 있는 비교과 프로그램을 안내해요.",
        category: "opportunity",
        posted_at: "2026-10-03T11:00:00+09:00",
        opportunity_id: course.id === "database" ? "database-hackathon" : null,
        attachments: [{ name: "프로그램 포스터.png", size_bytes: 979_532, status: "pending", file_id: null }],
      },
    ],
    // 계획서를 올리지 않은 과목은 일정도 없다(서버는 계획서 행이 있을 때만 준다). "데이터베이스"가
    // 그 상태라 목 모드에서 올리기 → 확인 → 확정 흐름을 그대로 돈다
    syllabus_items: course.has_syllabus
      ? [
          {
            id: `${course.id}-s1`,
            item_type: "midterm",
            title: "중간고사",
            starts_at: "2026-10-22T10:00:00+09:00",
            is_confirmed: true,
            calendar_registered: true, // 이미 캘린더에 들어간 일정(버튼이 안 보인다)
          },
          {
            id: `${course.id}-s2`,
            item_type: "assignment",
            title: "Homework 4",
            starts_at: "2026-10-13T23:59:00+09:00",
            is_confirmed: true,
            calendar_registered: false,
          },
          {
            id: `${course.id}-s3`,
            item_type: "presentation",
            title: "팀 발표",
            starts_at: "2026-11-12T14:00:00+09:00",
            is_confirmed: false,
            calendar_registered: false,
          },
        ]
      : [],
    materials: [
      {
        file_id: `${course.id}-material`,
        original_name: `${course.short_name}_8주차.pdf`,
        status: course.id === "database" ? "failed" : "succeeded", // 상한을 넘어 요약하지 않은 자료
      },
    ],
  };
}

export const courseDetails: Record<string, CourseDetail> = Object.fromEntries(
  courses.map((course, index) => [course.id, makeCourseDetail(course, index)]),
);

function makeMaterial(course: Course): MaterialDetail {
  const overLimit = course.id === "database"; // 상한을 넘은 자료(요약하지 않았다)
  return {
    file_id: `${course.id}-material`,
    file_name: `${course.short_name}_8주차.pdf`,
    course: { lms_course_id: course.id, name: course.short_name },
    source_language: null,
    total_pages: overLimit ? 184 : 42,
    processed_range: overLimit ? null : { start: 1, end: 42 },
    status: overLimit ? "failed" : "succeeded",
    overall_summary: overLimit
      ? null
      : `## 전체 요약\n${course.short_name} 8주차는 핵심 개념을 정의하고 예제로 익히는 자료예요.\n## 핵심 개념\n- 정의: 이번 주에 처음 나온 용어\n- 예제: 정의를 적용한 풀이\n## 시험 대비 포인트\n- 정의와 예제의 차이를 설명할 수 있어야 해요`,
    over_limit: overLimit,
    run_id: null,
  };
}

export const materials: Record<string, MaterialDetail> = Object.fromEntries(
  courses.map((course) => [`${course.id}-material`, makeMaterial(course)]),
);

export const lmsUpdates: LmsUpdate[] = [
  {
    type: "module_item",
    id: "analysis-m4",
    course: { id: "analysis", short_name: "해석학" },
    module_name: "8주차",
    title: "Decision Trees",
    item_type: "ExternalTool",
    html_url: "https://lms.example.edu/analysis/modules/4",
    first_seen_at: "2026-10-05T09:20:00+09:00",
    uploaded_file_id: "analysis-material",
  },
  {
    type: "assignment",
    id: "capstone-a1",
    course: { id: "capstone", short_name: "DS창업캡스톤디자인1" },
    title: "창업아이템 정의",
    due_at: "2026-10-06T23:59:00+09:00",
    submission_state: "unsubmitted",
    html_url: "https://lms.example.edu/capstone/assignments/1",
    first_seen_at: "2026-10-02T09:00:00+09:00",
  },
  {
    type: "announcement",
    id: "database-n1",
    course: { id: "database", short_name: "데이터베이스" },
    title: "다음 주 강의실 변경",
    summary: "제2공학관 301호에서 수업해요.",
    posted_at: "2026-10-05T08:00:00+09:00",
    category: "schedule_change",
    attachment_count: 0,
    opportunity_id: null,
    planner_task_id: "task-db-notice",
  },
];
