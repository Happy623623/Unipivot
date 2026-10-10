import type { Category, SourceType } from "@/types/api";

const KST_TIME_ZONE = "Asia/Seoul";

function parseDate(value: string | Date): Date {
  if (value instanceof Date) return value;
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00+09:00`) : new Date(value);
}

function getKstDateKey(value: string | Date): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: KST_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(parseDate(value));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function formatKstLongDate(value: string | Date): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST_TIME_ZONE,
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(parseDate(value));
}

export function formatKstShortDate(value: string | Date): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: KST_TIME_ZONE,
    month: "numeric",
    day: "numeric",
  }).format(parseDate(value));
}

export function formatKstDate(value: string | Date): string {
  return getKstDateKey(value).replace(/-/g, ".");
}

export function getDdayValue(
  deadlineAt: string | null,
  now: string | Date = new Date(),
): number | null {
  if (!deadlineAt) return null;
  const deadline = new Date(`${getKstDateKey(deadlineAt)}T00:00:00Z`);
  const today = new Date(`${getKstDateKey(now)}T00:00:00Z`);
  return Math.round((deadline.getTime() - today.getTime()) / 86_400_000);
}

export function formatDday(deadlineAt: string | null, now: string | Date = new Date()): string {
  const days = getDdayValue(deadlineAt, now);
  if (days === null) return "상시";

  if (days === 0) return "D-day";
  return days > 0 ? `D-${days}` : `D+${Math.abs(days)}`;
}

export function isDeadlineSoon(deadlineAt: string | null, now: string | Date = new Date()): boolean {
  const days = getDdayValue(deadlineAt, now);
  return days !== null && days >= 0 && days <= 3;
}

export function getCategoryLabel(category: Category, context: "feed" | "detail" = "feed"): string {
  if (context === "detail" && category === "research") return "연구 참여";
  if (context === "detail" && category === "exam") return "시험·자격";
  const labels: Record<Category, string> = {
    scholarship: "장학금",
    school_program: "교내 프로그램",
    youth_policy: "청년정책",
    contest: "공모전",
    activity: "대외활동",
    research: "연구",
    exam: "시험",
    etc: "기타",
  };
  return labels[category];
}

export function getSourceLabel(sourceType: SourceType): string {
  const labels: Record<SourceType, string> = {
    school_notice: "교내 공지",
    youth_policy: "청년정책",
    contest: "공모전",
    poster: "공유 포스터",
    lms_announcement: "과목 공지",
  };
  return labels[sourceType];
}

export function formatRelativeTime(
  value: string | Date,
  now: string | Date = new Date(),
): string {
  const elapsed = Math.max(
    0,
    parseDate(now).getTime() - parseDate(value).getTime(),
  );
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "방금 전";
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  return `${Math.floor(hours / 24)}일 전`;
}
