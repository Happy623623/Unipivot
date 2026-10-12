import Button from "@/components/Button";
import Header from "@/components/Header";
import type { Route } from "@/types/route";

// 실제 모드에서 포스터 등록(W6) API가 생기기 전까지 포스터 등록 화면 대신 보여 준다
export default function PosterNotReady({ navigate }: { navigate: (route: Route) => void }) {
  return (
    <>
      <Header title="포스터로 공고 등록" subtitle="포스터를 올리면 AI가 제목, 마감일, 지원 조건을 자동으로 정리해요." />
      <section className="flex min-h-[310px] flex-col items-center justify-center gap-3 rounded-[18px] border border-dashed border-[#e5e7eb] bg-white p-6 text-center">
        <p className="text-[18px] font-semibold">포스터 등록은 아직 준비 중이에요</p>
        <p className="text-[13px] text-[#667085]">준비되면 이 화면에서 포스터를 올려 공고로 등록할 수 있어요. 지금은 홈에서 학교 공지를 확인해 주세요.</p>
        <Button onClick={() => navigate({ name: "home" })}>홈으로</Button>
      </section>
    </>
  );
}
