import { getCategoryLabel } from "@/lib/format";
import type { PlannerTask } from "@/types/api";
import type { Tone } from "@/types/route";

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
