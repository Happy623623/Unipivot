import Skeleton from "@/components/Skeleton";

// 홈을 불러오는 동안의 자리(Home.tsx에서 옮김)
export function HomeSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[360px]" />
      <div className="grid max-w-[786px] grid-cols-3 gap-4">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-44 w-full rounded-2xl" />
      <Skeleton className="h-44 w-full rounded-2xl" />
    </>
  );
}

export interface EmptyState {
  title: string;
  action: string;
  onAction: () => void;
}

// 빈 목록 안내. 다음 행동 하나를 버튼으로 준다(Home.tsx에서 옮김)
export function EmptyBox({ title, action, onAction }: EmptyState) {
  return (
    <div className="mt-7 rounded-2xl border border-dashed border-[#e5e7eb] bg-white p-10 text-center">
      <p className="text-[16px] font-semibold">{title}</p>
      <button type="button" onClick={onAction} className="mt-3 text-[13px] font-semibold text-[#4f6ef7]">
        {action}
      </button>
    </div>
  );
}
