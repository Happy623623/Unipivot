import Badge from "@/components/Badge";
import Button from "@/components/Button";

type Tone = "red" | "yellow";

// 포스터 등록이 멈춘 자리(올리기 실패·분석 실패·한도 초과·시간 초과). 다음 행동 하나를 함께 둔다
export default function PosterNotice({
  tone,
  badge,
  title,
  action,
  onAction,
}: {
  tone: Tone;
  badge: string;
  title: string;
  action: string;
  onAction: () => void;
}) {
  return (
    <section className="flex min-h-[310px] flex-col items-center justify-center rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center">
      <Badge tone={tone}>{badge}</Badge>
      <h2 className="mt-4 text-[20px] font-bold">{title}</h2>
      <div className="mt-5">
        <Button onClick={onAction}>{action}</Button>
      </div>
    </section>
  );
}
