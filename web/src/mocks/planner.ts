import type { PlannerResponse } from "@/types/api";

export const planner: PlannerResponse = {
  items: [
    { id: "task-student-cert", title: "재학증명서 발급", due_date: "2026-10-05", is_done: true, source: "prep_plan", link: { type: "opportunity", id: "hanyang-support-2026", title: "2026 ERICA 생활지원 장학금", category: "scholarship" } },
    { id: "task-capstone-submit", title: "캡스톤 과제 제출", due_date: "2026-10-05", is_done: false, source: "lms_assignment", link: { type: "lms_assignment", id: "capstone-a1", title: "DS창업캡스톤디자인1", category: null, html_url: "https://lms.example.edu/a1" } },
    { id: "task-grade-cert", title: "성적증명서 준비", due_date: "2026-10-07", is_done: false, source: "prep_plan", link: { type: "opportunity", id: "hanyang-support-2026", title: "2026 ERICA 생활지원 장학금", category: "scholarship" } },
    { id: "task-db-quiz", title: "데이터베이스 퀴즈 제출", due_date: "2026-10-08", is_done: true, source: "lms_assignment", link: { type: "lms_assignment", id: "database-a1", title: "데이터베이스", category: null }, auto_completed: true },
    { id: "task-application", title: "장학금 신청서 작성", due_date: "2026-10-09", is_done: false, source: "prep_plan", link: { type: "opportunity", id: "hanyang-support-2026", title: "2026 ERICA 생활지원 장학금", category: "scholarship" } },
    { id: "task-scholarship-submit", title: "생활지원 장학금 최종 제출", due_date: "2026-10-10", is_done: false, source: "prep_plan", link: { type: "opportunity", id: "hanyang-support-2026", title: "2026 ERICA 생활지원 장학금", category: "scholarship" } },
    { id: "task-linear-homework", title: "선형대수 Homework 4", due_date: "2026-10-13", is_done: false, source: "syllabus", link: { type: "syllabus_item", id: "linear-s2", title: "선형대수", category: null } },
    { id: "task-analysis-review", title: "해석학 중간고사 복습", due_date: "2026-10-16", is_done: false, source: "manual", link: { type: null, id: null, title: null, category: null } },
    { id: "task-db-notice", title: "데이터베이스 강의실 변경 확인", due_date: "2026-10-19", is_done: false, source: "lms_announcement", link: { type: "lms_announcement", id: "database-n1", title: "데이터베이스", category: null } },
    { id: "task-contest-team", title: "도시 아이디어 공모전 팀 회의", due_date: "2026-10-22", is_done: false, source: "manual", link: { type: "opportunity", id: "city-idea-contest", title: "2026 대학생 도시 아이디어 공모전", category: "contest" } },
  ],
  markers: [
    { kind: "deadline", date: "2026-10-10", title: "생활지원 장학금 마감", opportunity_id: "hanyang-support-2026", category: "scholarship" },
    { kind: "deadline", date: "2026-10-23", title: "도시 아이디어 공모전 마감", opportunity_id: "city-idea-contest", category: "contest" },
  ],
};
