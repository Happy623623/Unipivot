import Badge from "@/components/Badge";
import type { RunStatus } from "@/types/api";

export interface AnalyzeStep {
  label: string;
  status: RunStatus;
}

const TONE: Partial<Record<RunStatus, "green" | "red">> = { succeeded: "green", failed: "red" };
const TEXT: Record<RunStatus, string> = {
  pending: "대기",
  running: "진행 중",
  succeeded: "완료",
  failed: "실패",
};

// 포스터를 분석하는 동안 보여 주는 단계 목록. 실제 모드는 실행의 처리 과정(F-42)을 그대로 보여 준다
export default function PosterAnalyzing({ steps }: { steps: AnalyzeStep[] }) {
  return (
    <section className="rounded-[18px] border border-[#e5e7eb] bg-white p-6" role="status">
      <h2 className="text-[20px] font-bold">포스터를 분석하고 있어요</h2>
      <div className="mt-5 flex flex-col gap-3">
        {steps.map((step) => (
          <div key={step.label} className="flex items-center justify-between rounded-[12px] bg-[#f7f8fa] p-4 text-[14px]">
            <span>{step.label}</span>
            <Badge tone={TONE[step.status] ?? "blue"}>{TEXT[step.status]}</Badge>
          </div>
        ))}
      </div>
    </section>
  );
}
