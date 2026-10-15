import Badge from "@/components/Badge";
import Button from "@/components/Button";

// 파일은 올렸지만 포스터에서 공고를 뽑는 기능(W6 2차)은 아직일 때 보여 준다
export default function PosterStored({
  onHome,
  onPickAgain,
}: {
  onHome: () => void;
  onPickAgain: () => void;
}) {
  return (
    <section className="flex min-h-[300px] flex-col items-center justify-center rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center">
      <Badge tone="green">업로드 완료</Badge>
      <h2 className="mt-4 text-[20px] font-bold">포스터를 올렸어요</h2>
      <p className="mt-2 text-[14px] text-[#667085]">
        제목·마감일·지원 조건을 자동으로 정리하는 기능은 준비 중이에요. 지금은 홈에서 학교 공지를 확인해 주세요.
      </p>
      <div className="mt-5 flex gap-2">
        <Button onClick={onHome}>홈으로</Button>
        <Button secondary onClick={onPickAgain}>다른 포스터 올리기</Button>
      </div>
    </section>
  );
}
