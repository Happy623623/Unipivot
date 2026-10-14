import { useEffect, useRef, type RefObject } from "react";

// 다음 그리기 뒤에 초점을 둘 홈 카드(카드의 data-card 버튼). index는 화면에 보이는 카드 순서다(목록 뒤에 펼친 묶음).
// leave: 표시를 바꿔 카드가 빠진 자리. 같은 순서의 카드, 맨 끝이면 앞 카드, 카드가 없으면 지금 탭 버튼
// back: 저장하지 못해 돌아온 카드. leave·back은 빠진 카드와 함께 초점을 잃었을 때만 옮긴다(그새 다른 곳을 눌렀으면 그대로 둔다)
// page: 쪽을 넘긴 목록의 첫 카드(화면은 목록 머리로 이미 올렸다). reveal: 안내의 "…보기"로 찾아간 카드(화면 가운데로)
// 목록을 다시 받는 중이라 목록이 없으면 요청을 들고 있다가 목록이 나타난 뒤 옮긴다
export type CardFocus = { kind: "leave" | "page"; index: number } | { kind: "back" | "reveal"; id: string };

export default function useCardFocus(listRef: RefObject<HTMLElement | null>) {
  const want = useRef<CardFocus | null>(null);
  useEffect(() => {
    const request = want.current;
    const list = listRef.current;
    if (!request || !list) return;
    want.current = null;
    const active = list.ownerDocument.activeElement;
    const lost = !active || active === list.ownerDocument.body;
    if ((request.kind === "leave" || request.kind === "back") && !lost) return;
    const cards = [...list.querySelectorAll<HTMLElement>("[data-card]")];
    const card =
      "id" in request ? cards.find((entry) => entry.dataset.card === request.id) : cards[Math.min(request.index, cards.length - 1)];
    if (request.kind === "reveal") card?.scrollIntoView({ block: "center" });
    const scrolled = request.kind === "page" || (request.kind === "reveal" && card !== undefined);
    (card ?? list.querySelector<HTMLElement>('[role="group"] [aria-pressed="true"]'))?.focus({ preventScroll: scrolled });
  });
  return want;
}
