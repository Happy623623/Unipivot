import Badge from "@/components/Badge";
import type { DisplayStatus } from "@/types/api";
import type { Tone } from "@/types/route";

interface StatusBadgeProps {
  displayStatus: DisplayStatus;
}

const statusMeta: Record<DisplayStatus, { label: string; tone: Tone }> = {
  eligible: { label: "지원 가능", tone: "green" },
  missing_info: { label: "정보 필요", tone: "yellow" },
  needs_review: { label: "원문 확인 필요", tone: "gray" },
  ineligible: { label: "지원 어려움", tone: "red" },
};

export default function StatusBadge({ displayStatus }: StatusBadgeProps) {
  const status = statusMeta[displayStatus];
  return <Badge tone={status.tone}>{status.label}</Badge>;
}
