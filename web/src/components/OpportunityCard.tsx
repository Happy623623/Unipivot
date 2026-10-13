import Badge from "@/components/Badge";
import OpportunityMarkButtons from "@/components/OpportunityMarkButtons";
import StatusBadge from "@/components/StatusBadge";
import { formatDdayValue, getCategoryLabel, getSourceLabel } from "@/lib/format";
import type { DisplayStatus, OpportunityItem, OpportunityMark } from "@/types/api";
import type { Route } from "@/types/route";

const statusMarks: Record<DisplayStatus, string> = {
  eligible: "✓",
  missing_info: "!",
  needs_review: "□",
  ineligible: "×",
};

interface OpportunityCardProps {
  item: OpportunityItem; // my_mark는 화면에서 바꾼 표시까지 반영한 값
  pending: boolean; // 표시를 저장하는 중
  navigate: (route: Route) => void;
  onMark: (item: OpportunityItem, next: OpportunityMark | null) => void;
}

// 홈 공고 카드. 카드를 누르면 상세로 가고, 오른쪽 아래 관심·숨기기는 카드 버튼과 따로 눌린다.
// data-card는 표시를 바꿔 카드가 탭에서 빠질 때 홈이 다음 카드로 초점을 옮기는 데 쓴다
export default function OpportunityCard({ item, pending, navigate, onMark }: OpportunityCardProps) {
  const displayStatus = item.eligibility.display_status;
  const reasonTone =
    displayStatus === "eligible"
      ? "bg-[#ecfdf3] text-[#15803d]"
      : displayStatus === "missing_info"
        ? "bg-[#fff8e1] text-[#b7791f]"
        : displayStatus === "needs_review"
          ? "bg-[#f2f4f7] text-[#475467]"
          : "bg-[#fef2f2] text-[#c53030]";
  const deadlineSoon = item.d_day !== null && item.d_day >= 0 && item.d_day <= 3;
  // 포스터는 올린 사람에게만 보인다. 업로더 이름 대신 "내가 올린 포스터"라고 쓴다
  const context =
    item.source_type === "poster" && item.uploaded_by_me
      ? "내가 올린 포스터"
      : item.source_type === "lms_announcement" && item.course_name
        ? `${item.course_name} 수강생 대상`
        : null;
  const sourceAction = item.source_type === "poster" ? "포스터 보기" : "원문 보기";
  const titleId = `opportunity-title-${item.id}`;

  return (
    <div className="opportunity-card relative w-full rounded-2xl border border-[#e5e7eb] bg-white transition-all duration-300 hover:-translate-y-1 hover:border-[#cfd7ff] hover:shadow-[0_14px_36px_rgba(79,110,247,0.11)]">
      <button
        type="button"
        data-card={item.id}
        onClick={() => navigate({ name: "opportunity", id: item.id })}
        className="w-full rounded-2xl p-[22px] text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f6ef7]"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{getCategoryLabel(item.category)}</Badge>
            <span className="text-[12px] font-medium text-[#667085]">{item.organizer}</span>
            {context && <span className="text-[12px] text-[#667085]">· {context}</span>}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <StatusBadge displayStatus={displayStatus} />
            {item.eligibility.display_status === "eligible" && item.needs_review && (
              <Badge tone="gray">원문 확인 필요</Badge>
            )}
            <span className={`text-[12px] font-semibold ${deadlineSoon ? "text-[#c53030]" : "text-[#667085]"}`}>
              {deadlineSoon && "마감 임박 "}
              {formatDdayValue(item.d_day)}
            </span>
          </div>
        </div>
        <h3 id={titleId} className="mt-3 flex items-center gap-2 text-[18px] font-semibold leading-[1.45]">
          {item.is_new && <span className="size-2 shrink-0 rounded-full bg-[#4f6ef7]" />}
          {item.title}
        </h3>
        <p className="mt-2 text-[13px] text-[#667085]">{item.easy_summary}</p>
        {/* 사유가 길면(청년정책의 기타 조건 글) 카드 너비에서 말줄임한다 */}
        <div className={`mt-3 inline-flex max-w-full items-center gap-2 rounded-[10px] px-3 py-[9px] text-[13px] font-medium ${reasonTone}`}>
          <b>{statusMarks[displayStatus]}</b>
          <span className="min-w-0 truncate">{item.eligibility.summary}</span>
        </div>
        {/* 오른쪽 아래 관심·숨기기 자리를 비워 둔다. 좁은 화면에서는 글이 줄을 바꾼다 */}
        <p className="mt-3 pr-[148px] text-[12px] leading-[26px] text-[#667085]">
          {getSourceLabel(item.source_type)} · {sourceAction}
        </p>
      </button>
      <div className="absolute bottom-[22px] right-[22px]">
        <OpportunityMarkButtons
          mark={item.my_mark}
          pending={pending}
          describedBy={titleId}
          onChange={(next) => onMark(item, next)}
        />
      </div>
    </div>
  );
}
