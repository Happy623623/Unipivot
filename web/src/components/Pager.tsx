import { pageNumbers } from "@/lib/paginate";

interface PagerProps {
  label: string; // 화면 읽기 프로그램이 읽는 쪽 줄 이름(예: "공고 목록 쪽")
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
}

// 한 칸(번호·이전·다음·줄임표). 아홉 칸이 320px 화면에도 한 줄로 들어가게 좁은 화면에서는 칸을 줄인다
const cell = "flex size-8 items-center justify-center max-[359px]:size-7";

// 쪽 번호와 이전·다음. 한 쪽뿐이면 그리지 않는다. 끝 쪽의 이전·다음은 초점을 잃지 않게 aria-disabled로 막는다.
// 줄임표도 번호 버튼과 같은 칸을 차지해 쪽을 넘겨도 줄 너비가 같다
export default function Pager({ label, page, pageCount, onChange }: PagerProps) {
  if (pageCount <= 1) return null;
  const go = (next: number) => {
    if (next >= 1 && next <= pageCount && next !== page) onChange(next);
  };
  const base = `${cell} rounded-[10px] text-[13px] font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f6ef7]`;
  const step = `${base} text-[#667085] hover:bg-white aria-disabled:cursor-default aria-disabled:text-[#a0a4ab] aria-disabled:hover:bg-transparent`;
  return (
    <nav aria-label={label} className="mt-6 flex flex-wrap items-center justify-center gap-1 max-[359px]:gap-0.5">
      <button type="button" aria-label="이전 쪽" aria-disabled={page === 1} onClick={() => go(page - 1)} className={step}>
        ‹
      </button>
      {pageNumbers(page, pageCount).map((value, index) =>
        value === "gap" ? (
          <span key={`gap-${index}`} aria-hidden="true" className={`${cell} text-[13px] text-[#a0a4ab]`}>
            …
          </span>
        ) : (
          <button
            key={value}
            type="button"
            aria-label={`${value}쪽`}
            aria-current={value === page ? "page" : undefined}
            onClick={() => go(value)}
            className={`${base} ${value === page ? "bg-[#4f6ef7] text-white" : "text-[#667085] hover:bg-white"}`}
          >
            {value}
          </button>
        ),
      )}
      <button type="button" aria-label="다음 쪽" aria-disabled={page === pageCount} onClick={() => go(page + 1)} className={step}>
        ›
      </button>
    </nav>
  );
}
