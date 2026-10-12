import { useState } from "react";
import Badge from "@/components/Badge";
import { formatKstDate } from "@/lib/format";
import type { OpportunityDetail, RunStatus } from "@/types/api";
import type { Tone } from "@/types/route";

interface AiProcessPanelProps {
  detail: OpportunityDetail;
}

const STEP_STATUS: Record<RunStatus, { label: string; tone: Tone }> = {
  succeeded: { label: "완료", tone: "green" },
  failed: { label: "실패", tone: "red" },
  running: { label: "진행 중", tone: "blue" },
  pending: { label: "대기", tone: "gray" },
};

// AI 처리 과정(F-42): 요건 추출 단계, 원문 확인이 필요한 이유, 프로필 비교, 준비 단계.
// 단계의 고른 이유(note)와 원문 확인 이유는 모델이 쓴 글이라 일반 텍스트로만 보여 준다(링크·마크다운 없이)
export default function AiProcessPanel({ detail }: AiProcessPanelProps) {
  const [open, setOpen] = useState(false);
  const steps = detail.process.extraction;
  const evaluatedAt = detail.eligibility.evaluated_at;
  const empty = steps.length === 0 && detail.review_reasons.length === 0 && !evaluatedAt && !detail.prep.prepared;

  return (
    <section className="rounded-[14px] bg-[#eef2ff] p-[18px]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between text-[14px] font-semibold text-[#4f6ef7]"
      >
        AI 처리 과정
        <span>{open ? "⌃" : "⌄"}</span>
      </button>
      {open && (
        <div className="mt-4 flex flex-col gap-2">
          {detail.review_reasons.length > 0 && (
            <div className="rounded-[10px] bg-white/70 px-4 py-3 text-[13px] text-[#344054]">
              <p className="font-semibold">원문 확인이 필요한 이유</p>
              <ul className="mt-1 list-disc pl-5 leading-6">
                {detail.review_reasons.map((reason, index) => <li key={index}>{reason}</li>)}
              </ul>
            </div>
          )}
          {steps.map((step) => {
            const status = STEP_STATUS[step.status];
            return (
              <div key={step.seq} className="rounded-[10px] bg-white/70 px-4 py-3 text-[13px]">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex flex-wrap items-center gap-2">
                    {step.label}
                    {step.chosen_by === "agent" && <Badge tone="blue">AI가 고름</Badge>}
                  </span>
                  <span className="flex shrink-0 items-center gap-2 text-[#667085]">
                    {step.latency_ms !== null && `${step.latency_ms}ms`}
                    <Badge tone={status.tone}>{status.label}</Badge>
                  </span>
                </div>
                {step.note && <p className="mt-1 text-[12px] leading-5 text-[#667085]">{step.note}</p>}
              </div>
            );
          })}
          {evaluatedAt && (
            <div className="rounded-[10px] bg-white/70 px-4 py-3 text-[13px] text-[#344054]">
              내 프로필과 비교 · {formatKstDate(evaluatedAt)}
            </div>
          )}
          {detail.prep.prepared && (
            <>
              <div className="flex justify-between rounded-[10px] bg-white/70 px-4 py-3 text-[13px]">
                <span>필요 서류 확인</span><Badge tone="green">완료</Badge>
              </div>
              <div className="flex justify-between rounded-[10px] bg-white/70 px-4 py-3 text-[13px]">
                <span>마감일에서 거꾸로 일정 짜기</span><Badge tone="green">완료</Badge>
              </div>
            </>
          )}
          {empty && <p className="px-1 text-[13px] text-[#667085]">아직 AI 처리 기록이 없어요.</p>}
        </div>
      )}
    </section>
  );
}
