import Badge from "@/components/Badge";
import Button from "@/components/Button";

// 올린 포스터가 이미 등록된 공고일 때. 그 공고로 갈 수 있게 한다(API 명세 6장)
export default function PosterDuplicate({
  title,
  onOpen,
  onPickAgain,
}: {
  title: string;
  onOpen: () => void;
  onPickAgain: () => void;
}) {
  return (
    <section className="flex min-h-[300px] flex-col items-center justify-center rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center">
      <Badge tone="yellow">중복 공고</Badge>
      <h2 className="mt-4 text-[22px] font-bold">이미 등록된 공고예요</h2>
      <p className="mt-2 text-[14px] text-[#667085]">{title}</p>
      <div className="mt-5 flex gap-2">
        <Button onClick={onOpen}>기존 공고 보기</Button>
        <Button secondary onClick={onPickAgain}>다른 포스터 올리기</Button>
      </div>
    </section>
  );
}
