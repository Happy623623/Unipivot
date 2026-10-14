// 홈 공고 목록 쪽 나누기(F-40). 한 쪽에 5개씩이다
export const PAGE_SIZE = 5;

// 고른 쪽. key는 목록이 무엇인지(탭·카테고리·정렬·요약 카드 거르기)이고, 목록이 바뀌면 1쪽으로 돌아간다
export interface PageAt {
  key: string;
  page: number;
}

export interface Paged<T> {
  page: number;
  pageCount: number;
  items: T[];
}

// 공고가 빠져 쪽 수가 줄면 마지막 쪽에 머문다
export function paginate<T>(items: T[], at: PageAt, key: string): Paged<T> {
  const pageCount = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const page = Math.min(at.key === key ? at.page : 1, pageCount);
  return { page, pageCount, items: items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE) };
}

// 목록에서 index번째(0부터) 공고가 있는 쪽
export function pageOf(index: number): number {
  return Math.floor(index / PAGE_SIZE) + 1;
}

// 쪽 번호 줄. 7쪽까지는 다 보인다. 넘으면 처음·끝·지금 쪽과 그 앞뒤를 보이고 사이는 "gap"(…)으로 줄이되,
// 처음·끝 가까이에서는 번호를 더 보여 늘 일곱 칸이다. 그래서 쪽을 넘겨도 이전·다음 버튼이 제자리에 있다
export function pageNumbers(page: number, pageCount: number): (number | "gap")[] {
  const run = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, index) => from + index);
  if (pageCount <= 7) return run(1, pageCount);
  if (page <= 4) return [...run(1, 5), "gap", pageCount];
  if (page >= pageCount - 3) return [1, "gap", ...run(pageCount - 4, pageCount)];
  return [1, "gap", page - 1, page, page + 1, "gap", pageCount];
}
