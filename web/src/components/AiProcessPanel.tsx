import { useState } from "react";
import Badge from "@/components/Badge";
import { formatKstDate } from "@/lib/format";
import type { OpportunityDetail } from "@/types/api";

interface AiProcessPanelProps {
  detail: OpportunityDetail;
}

export default function AiProcessPanel({ detail }: AiProcessPanelProps) {
  const [open, setOpen] = useState(false);

  return (
    <section className="rounded-[14px] bg-[#eef2ff] p-[18px]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between text-[14px] font-semibold text-[#4f6ef7]"
      >
        AI 처리 과정
        <span>{open ? "⌃" : "⌄"}</span>
      </button>
      {open && (
        <div className="mt-4 flex flex-col gap-2">
          {detail.process.extraction.map((step) => (
            <div key={step.seq} className="flex items-center justify-between rounded-[10px] bg-white/70 px-4 py-3 text-[13px]">
              <span>{step.label}</span>
              <span className="flex items-center gap-2 text-[#667085]">
                {step.latency_ms !== null ? `${step.latency_ms}ms` : "측정 중"}
                <Badge tone={step.status === "succeeded" ? "green" : "blue"}>
                  {step.status === "succeeded" ? "완료" : "진행 중"}
                </Badge>
              </span>
            </div>
          ))}
          <div className="rounded-[10px] bg-white/70 px-4 py-3 text-[13px] text-[#344054]">
            내 프로필과 비교 · {formatKstDate(detail.eligibility.evaluated_at)}
          </div>
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
        </div>
      )}
    </section>
  );
}
