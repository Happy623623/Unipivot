import { useEffect, useRef } from "react";

// 다른 화면으로 옮기면(주소의 경로가 바뀜) 누른 것(알림 줄·"모든 알림 확인하기"·공고 카드 등)이 사라져 초점이 <body>로
// 빠진다. 새 화면의 제목(main의 h1)으로 옮겨 화면 읽기 프로그램이 새 화면 이름을 읽고, Tab이 그 화면에서 이어지게 한다.
// 처음 열 때와, 누른 것에 초점이 아직 남아 있을 때(Chrome에서 사이드바 버튼을 누름)는 그대로 둔다 — Safari·macOS
// Firefox는 마우스로 누른 버튼에 초점을 주지 않아 사이드바로 옮겨도 제목으로 간다(마우스라 테두리는 안 보인다).
// 새 화면은 데이터를 받은 뒤에 제목을 그리기도 해서, 제목이 생길 때까지 조금(최대 WAIT_MS) 기다린다.
// 기다리는 동안 사용자가 다른 곳에 초점을 두거나 창이 열리면(?focus=profile_input으로 바로 열리는 정보 입력 창 —
// 창이 초점을 잡기 전 한 프레임에 제목이 끼어들면 창의 돌아갈 곳이 바뀐다, 검토) 그만둔다
const WAIT_MS = 3000;

function focusLost(): boolean {
  return document.activeElement === document.body || document.activeElement === null;
}

// 열린 창(닫힌 알림 패널은 inert라 빠진다)
function dialogOpen(): boolean {
  return document.querySelector('[role="dialog"][aria-modal="true"]:not([inert])') !== null;
}

export default function useRouteFocus(pathname: string): void {
  // 이전 경로와 비교한다. "처음인지" 플래그는 StrictMode(개발)가 효과를 한 번 더 돌리면 처음에도 옮겨 버린다(검토)
  // 옮길 일이 남은 경로. StrictMode가 효과를 지웠다 다시 돌려도(정리에서 프레임을 취소한다) 이어서 기다린다
  const previous = useRef(pathname);
  const pending = useRef<{ pathname: string; startedAt: number } | null>(null);

  useEffect(() => {
    if (previous.current !== pathname) {
      previous.current = pathname;
      pending.current = { pathname, startedAt: Date.now() };
    }
    const job = pending.current;
    if (!job || job.pathname !== pathname) return;
    const { startedAt } = job;
    let frame = 0;
    const done = () => {
      if (pending.current === job) pending.current = null;
    };
    const tryFocus = () => {
      // 누른 것이 남았거나, 사용자가 이미 다른 곳에 있거나, 창이 맡는다
      if (!focusLost() || dialogOpen()) return done();
      // 보이는 제목만(이전 화면을 숨겨 남기는 설정이 켜지면 숨은 옛 제목이 먼저 잡힌다, 검토)
      const heading = [...document.querySelectorAll<HTMLElement>("main h1")].find(
        (element) => element.getClientRects().length > 0,
      );
      heading?.focus({ preventScroll: true });
      if (document.activeElement === heading) return done();
      if (Date.now() - startedAt < WAIT_MS) frame = requestAnimationFrame(tryFocus);
      else done();
    };
    frame = requestAnimationFrame(tryFocus);
    return () => cancelAnimationFrame(frame);
  }, [pathname]);
}
