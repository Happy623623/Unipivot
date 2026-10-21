import type { RefObject } from "react";
import { errorMessage, getAlternatives } from "@/api/client";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Skeleton from "@/components/Skeleton";
import { formatDdayValue, getCategoryLabel } from "@/lib/format";
import useAsyncData from "@/lib/useAsyncData";
import type { Route } from "@/types/route";

interface OpportunityAlternativesProps {
  opportunityId: string;
  judgedKey: string; // 판정이 바뀌면(정보 입력 뒤·요건을 다시 읽음) 목록도 다시 받는다. 서류 체크처럼 상세만 다시 받을 때는 그대로다
  headingRef: RefObject<HTMLHeadingElement | null>; // 위의 "대체 공고 보기"가 초점을 옮기는 곳
  navigate: (route: Route) => void;
}

const FAILED = "대체 공고를 불러오지 못했어요. 잠시 후 이 화면을 다시 열어 주세요.";

// 지원 어려움 공고의 대체 공고(F-23). 같은 카테고리의 지원 가능 공고를 필수 서류 수가 비슷한 순으로 최대 3개 보여 준다
export default function OpportunityAlternatives({ opportunityId, judgedKey, headingRef, navigate }: OpportunityAlternativesProps) {
  const request = useAsyncData(
    () =>
      getAlternatives(opportunityId).catch((error: unknown) => {
        throw new Error(errorMessage(error, FAILED));
      }),
    [opportunityId, judgedKey],
  );
  const items = request.data ?? [];

  return (
    <section aria-labelledby="alternatives-title" aria-busy={request.loading} className="rounded-2xl border border-[#e5e7eb] bg-white p-[22px]">
      <h2
        id="alternatives-title"
        ref={headingRef}
        tabIndex={-1}
        className="text-[18px] font-semibold outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f6ef7]"
      >
        대체 공고
      </h2>
      <p className="mt-2 text-[13px] text-[#667085]">같은 분야에서 지금 지원할 수 있는 공고예요. 필수 서류 수가 비슷한 순이에요.</p>
      {request.loading ? (
        <Skeleton className="mt-4 h-[96px] w-full rounded-[14px]" />
      ) : request.error ? (
        <p role="status" className="mt-4 rounded-[10px] bg-[#fef2f2] px-3 py-2 text-[13px] text-[#c53030]">{request.error}</p>
      ) : items.length === 0 ? (
        <div className="mt-4 flex items-center justify-between gap-3 max-[760px]:flex-col max-[760px]:items-start">
          <p className="text-[14px] text-[#344054]">같은 분야에서 지금 지원할 수 있는 공고가 없어요. 홈에서 다른 공고를 둘러보세요.</p>
          <Button secondary onClick={() => navigate({ name: "home" })}>홈으로</Button>
        </div>
      ) : (
        <ul className="mt-4 grid gap-3">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => navigate({ name: "opportunity", id: item.id })}
                className="w-full rounded-[14px] border border-[#e5e7eb] p-4 text-left hover:border-[#cfd7ff] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f6ef7]"
              >
                {/* 화면 읽기 프로그램이 제목부터 읽도록 제목을 앞에 둔다 */}
                <span className="block text-[15px] font-semibold">{item.title}</span>
                <span className="mt-2 flex items-center justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2">
                    <Badge>{getCategoryLabel(item.category)}</Badge>
                    {item.needs_review && <Badge tone="gray">원문 확인 필요</Badge>}
                    <span className="truncate text-[12px] text-[#667085]">{item.organizer}</span>
                  </span>
                  <span className="shrink-0 text-[12px] font-semibold text-[#667085]">{formatDdayValue(item.d_day)}</span>
                </span>
                {item.recommend_reason && (
                  <span className="mt-2 block text-[12px] font-medium text-[#344054]">추천 이유 · {item.recommend_reason}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
