import { ApiError, errorMessage } from "@/api/client";
import type { OpportunityMark } from "@/types/api";

interface OpportunityMarkButtonsProps {
  mark: OpportunityMark | null;
  pending: boolean; // 저장하는 중. 초점을 잃지 않게 disabled 대신 aria-disabled로 막는다
  describedBy?: string; // 카드에서는 공고 제목 id. 카드마다 같은 버튼 이름을 제목으로 구분한다
  onChange: (next: OpportunityMark | null) => void;
}

// 표시를 바꾼 뒤 띄우는 안내. 버튼과 같은 이름을 쓴다(관심, 숨기기, 숨김 풀기).
// 홈은 안내에 "숨김 탭 보기" 버튼이 붙어 숨긴 공고를 어디서 보는지 따로 쓰지 않는다
export function markToast(
  before: OpportunityMark | null,
  next: OpportunityMark | null,
  where: "home" | "detail" = "detail",
): string {
  if (next === "interested") {
    return before === "not_interested" ? "숨김을 풀고 관심 공고에 담았어요" : "관심 공고에 담았어요";
  }
  if (next === "not_interested") {
    const done = before === "interested" ? "관심 공고에서 빼고 숨겼어요" : "숨겼어요";
    return where === "home" ? done : `${done}. 홈의 숨김 탭에서 다시 볼 수 있어요`;
  }
  return before === "not_interested" ? "숨김을 풀었어요" : "관심 공고에서 뺐어요";
}

// 표시를 바꾸지 못했을 때. 그새 목록에서 내린 공고(404)는 새로 고치라고 알린다
export function markError(error: unknown): string {
  if (error instanceof ApiError && error.code === "NOT_FOUND") {
    return "지금은 목록에서 내린 공고예요. 화면을 새로 고쳐 주세요.";
  }
  return errorMessage(error, "저장하지 못했어요. 잠시 후 다시 눌러 주세요.");
}

// 관심·숨기기(F-45, 카드와 상세). 공고마다 표시는 하나다. 관심을 다시 누르면 풀고, 숨긴 공고는 숨김 풀기로 되돌린다
export default function OpportunityMarkButtons({ mark, pending, describedBy, onChange }: OpportunityMarkButtonsProps) {
  const interested = mark === "interested";
  const hidden = mark === "not_interested";
  const press = (next: OpportunityMark | null) => {
    if (!pending) onChange(next);
  };
  const base =
    "shrink-0 rounded-full px-2.5 py-1 text-[12px] font-semibold transition-colors aria-disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f6ef7]";
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        aria-pressed={interested}
        aria-disabled={pending}
        aria-describedby={describedBy}
        onClick={() => press(interested ? null : "interested")}
        className={`${base} ${interested ? "bg-[#eef2ff] text-[#4f6ef7]" : "text-[#667085] hover:bg-[#f2f4f7]"}`}
      >
        <span aria-hidden="true">{interested ? "★" : "☆"}</span> 관심
      </button>
      <button
        type="button"
        aria-disabled={pending}
        aria-describedby={describedBy}
        onClick={() => press(hidden ? null : "not_interested")}
        className={`${base} text-[#667085] hover:bg-[#f2f4f7]`}
      >
        {hidden ? "숨김 풀기" : "숨기기"}
      </button>
    </div>
  );
}
