import Badge from "@/components/Badge";
import { formatDday } from "@/lib/format";
import { MOCK_TODAY } from "@/api/client";
import type { CourseDetail, SubmissionState } from "@/types/api";
import type { Tone } from "@/types/route";

interface CourseAssignmentsProps {
  assignments: CourseDetail["assignments"];
}

const submissionMeta: Record<SubmissionState, { label: string; tone: Tone }> = {
  unsubmitted: { label: "미제출", tone: "red" },
  submitted: { label: "제출", tone: "green" },
  graded: { label: "채점 완료", tone: "gray" },
  pending_review: { label: "제출", tone: "green" },
};

export default function CourseAssignments({
  assignments,
}: CourseAssignmentsProps) {
  const sorted = [...assignments].sort((a, b) => {
    const aSubmitted = a.submission_state === "unsubmitted" ? 0 : 1;
    const bSubmitted = b.submission_state === "unsubmitted" ? 0 : 1;
    if (aSubmitted !== bSubmitted) return aSubmitted - bSubmitted;
    return (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999");
  });

  return (
    <div className="flex flex-col gap-3">
      {sorted.map((assignment) => {
        const status = submissionMeta[assignment.submission_state];
        return (
          <article
            key={assignment.id}
            className="flex items-center justify-between gap-4 rounded-[12px] bg-[#f7f8fa] p-4"
          >
            <div>
              <p className="text-[14px] font-semibold">{assignment.title}</p>
              <p className="mt-1 text-[12px] text-[#667085]">
                {assignment.due_at
                  ? `마감 ${formatDday(assignment.due_at, MOCK_TODAY)}`
                  : "마감일 없음"}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Badge tone={status.tone}>{status.label}</Badge>
              <a
                href={assignment.html_url}
                target="_blank"
                rel="noreferrer"
                className="text-[12px] font-semibold text-[#4f6ef7]"
              >
                LMS에서 제출
              </a>
            </div>
          </article>
        );
      })}
    </div>
  );
}
