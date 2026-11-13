import { getCategoryLabel } from "@/lib/format";
import type { PlannerTask } from "@/types/api";
import type { Route, Tone } from "@/types/route";

// 할 일을 누르면 갈 곳(피드백 4②). 공고 준비는 공고 상세, 과목에서 온 할 일은 그 과목의 탭이다.
// 직접 추가한 할 일과 과목을 모르는 계획서 일정(LMS 과목 없이 올린 계획서)은 갈 곳이 없다
export function plannerTaskRoute(task: PlannerTask): Route | null {
  const { link } = task;
  if (link.type === "opportunity" && link.id) return { name: "opportunity", id: link.id };
  if (!link.course_id) return null;
  if (link.type === "lms_assignment") return { name: "course", id: link.course_id, tab: "assignments" };
  if (link.type === "syllabus_item") return { name: "course", id: link.course_id, tab: "syllabus" };
  if (link.type === "lms_announcement") return { name: "course", id: link.course_id, tab: "announcements" };
  return null;
}

export function getPlannerTaskMeta(task: PlannerTask): {
  label: string;
  tone: Tone;
  chipClass: string;
} {
  if (task.source === "prep_plan") {
    return {
      label: task.link.category
        ? getCategoryLabel(task.link.category)
        : "공고 준비",
      tone: "blue",
      chipClass: "bg-[#eef2ff] text-[#4f6ef7]",
    };
  }
  if (
    task.source === "lms_assignment" ||
    task.source === "lms_announcement" ||
    task.source === "syllabus"
  ) {
    return {
      label: task.link.title ?? "LMS",
      tone: "red",
      chipClass: "bg-[#fef2f2] text-[#c53030]",
    };
  }
  return {
    label: "직접 추가",
    tone: "gray",
    chipClass: "bg-[#f2f4f7] text-[#475467]",
  };
}
