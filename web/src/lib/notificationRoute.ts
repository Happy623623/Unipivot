import type { AppNotification } from "@/types/api";
import type { Route } from "@/types/route";

// 알림을 누르면 갈 곳 (API 명세 10장). 갈 곳이 없는 알림(link: null)은 눌러도 읽음 처리만 한다
export default function notificationRoute(notification: AppNotification): Route | null {
  const link = notification.link;
  if (!link) return null;
  if (link.type === "opportunity") {
    return { name: "opportunity", id: link.id, focus: link.focus ?? undefined };
  }
  if (link.type === "planner_task") return { name: "planner" };
  // lms_* 알림의 link.id는 과제·자료·공지 ID라서 과목 이동에는 course_id를 쓴다
  const courseId = link.course_id;
  if (!courseId) return { name: "academics" };
  if (link.type === "lms_module_item") {
    return { name: "course", id: courseId, tab: "materials" };
  }
  if (link.type === "lms_announcement") {
    return { name: "course", id: courseId, tab: "announcements" };
  }
  // 출석 마감 알림(lecture_due)은 과목의 강의 탭으로 간다(11/27)
  if (link.type === "lms_course") {
    return { name: "course", id: courseId, tab: "lectures" };
  }
  return { name: "course", id: courseId, tab: "assignments" };
}
