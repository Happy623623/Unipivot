import type { AppNotification } from "@/types/api";

export const notifications: AppNotification[] = [
  { id: "notification-1", type: "deadline_soon", title: "창업 캠프 마감이 가까워요", body: "ERICA 창업 아이디어 캠프 마감까지 3일 남았어요.", scheduled_at: "2026-10-05T09:00:00+09:00", read_at: null, link: { type: "opportunity", id: "erica-startup-camp" } },
  { id: "notification-2", type: "new_assignment", title: "새 과제가 등록됐어요", body: "해석학 Homework 4를 확인하세요.", scheduled_at: "2026-10-05T08:40:00+09:00", read_at: null, link: { type: "lms_assignment", id: "analysis-a1", course_id: "analysis" } },
  { id: "notification-3", type: "profile_needed", title: "프로필 정보가 필요해요", body: "거주지를 입력하면 청년정책 지원 가능 여부를 판정할 수 있어요.", scheduled_at: "2026-10-05T08:10:00+09:00", read_at: null, link: { type: "opportunity", id: "youth-capability", focus: "profile_input" } },
  { id: "notification-4", type: "new_material", title: "새 강의자료가 등록됐어요", body: "선형대수 8주차 강의자료를 확인하세요.", scheduled_at: "2026-10-04T17:00:00+09:00", read_at: "2026-10-04T18:00:00+09:00", link: { type: "lms_module_item", id: "linear-algebra-m4", course_id: "linear-algebra" } },
  { id: "notification-5", type: "schedule_change", title: "강의실이 변경됐어요", body: "데이터베이스 수업은 제2공학관 301호에서 진행해요.", scheduled_at: "2026-10-04T14:00:00+09:00", read_at: "2026-10-04T15:00:00+09:00", link: { type: "lms_announcement", id: "database-n1", course_id: "database" } },
  { id: "notification-6", type: "task_due", title: "오늘 할 일이 있어요", body: "재학증명서 발급과 캡스톤 과제 제출을 확인하세요.", scheduled_at: "2026-10-04T09:00:00+09:00", read_at: "2026-10-04T10:00:00+09:00", link: { type: "planner_task", id: "task-student-cert" } },
];
