import Badge from "@/components/Badge";

export type StepStatus = "idle" | "running" | "done";

const labels = ["포스터에서 글자·날짜 읽기", "지원 자격 정리", "내 프로필과 비교"];

// 포스터를 분석하는 동안 보여 주는 단계 목록
export default function PosterAnalyzing({ steps }: { steps: StepStatus[] }) {
  return (
    <section className="rounded-[18px] border border-[#e5e7eb] bg-white p-6">
      <h2 className="text-[20px] font-bold">포스터를 분석하고 있어요</h2>
      <div className="mt-5 flex flex-col gap-3">
        {labels.map((label, index) => (
          <div key={label} className="flex items-center justify-between rounded-[12px] bg-[#f7f8fa] p-4 text-[14px]">
            <span>{label}</span>
            <Badge tone={steps[index] === "done" ? "green" : "blue"}>
              {steps[index] === "done" ? "완료" : steps[index] === "running" ? "진행 중" : "대기"}
            </Badge>
          </div>
        ))}
      </div>
    </section>
  );
}
