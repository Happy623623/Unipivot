import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { useAppShell } from "@/components/AppShell";
import NotificationRow from "@/components/NotificationRow";
import Skeleton from "@/components/Skeleton";
import notificationRoute from "@/lib/notificationRoute";
import useDialogFocus from "@/lib/useDialogFocus";
import useNotifications from "@/lib/useNotifications";
import type { AppNotification } from "@/types/api";

// 한 쪽이 20줄이라 끝까지 시간차를 주면 마지막 줄이 1.3초 뒤에 보인다. 아홉째 줄부터는 같이 나타난다
const LAST_STAGGERED = 8;

interface NotificationPanelProps {
  open: boolean;
  onClose: () => void;
  // 연 버튼(헤더 종). 마우스로 눌러도 버튼에 초점을 주지 않는 브라우저(Safari 등)에서도 닫으면 여기로 돌아온다
  returnFocusRef?: RefObject<HTMLElement | null>;
}

// 헤더 알림 버튼이 여는 오른쪽 패널 (F-35). 최근 알림을 열 때마다 받아 오고, 전체 목록은 /notifications다.
// 알림을 누르면 읽음 처리를 기다리지 않고 바로 그 화면으로 간다(저장하지 못하면 안 읽음으로 되돌린다).
// 키보드 초점은 창(Modal)과 같다(lib/useDialogFocus.ts): 열면 패널 자체로(제목 "알림"을 읽는다), Tab은 패널 안에서 돌고,
// Esc로 닫히며, 닫히면 연 버튼(헤더 종)으로 돌아간다. 뒤 화면은 덮개로 가려 누르면 닫히므로 모달로 둔다
export default function NotificationPanel({ open, onClose, returnFocusRef }: NotificationPanelProps) {
  const { unreadNotifications, setUnreadNotifications, navigate } = useAppShell();
  const { items, unread, loading, error, reload, read, readAll } = useNotifications({ enabled: open });
  const [readFailed, setReadFailed] = useState(false);
  const [readNotice, setReadNotice] = useState(""); // "모두 읽음" 결과를 화면 읽기 프로그램에 알린다(알림함 화면은 토스트로 알린다)
  const panelRef = useRef<HTMLElement>(null);
  const titleId = useId();
  useDialogFocus(panelRef, open, onClose, returnFocusRef);

  useEffect(() => {
    if (unread !== null) setUnreadNotifications(unread);
  }, [unread, setUnreadNotifications]);

  useEffect(() => {
    if (open) {
      setReadFailed(false);
      setReadNotice("");
    }
  }, [open]);

  // 패널은 알림을 누르면 바로 다른 화면으로 가서, 읽음 처리 실패는 "모두 읽음"에서만 알린다
  const readEverything = async () => {
    const saved = await readAll();
    setReadFailed(!saved);
    setReadNotice(saved ? "알림을 모두 읽음으로 바꿨어요." : "읽음 처리를 저장하지 못했어요. 다시 눌러 주세요.");
  };

  const openNotification = (notification: AppNotification) => {
    void read(notification);
    const route = notificationRoute(notification);
    onClose();
    if (route) navigate(route);
  };

  return (
    <>
      <div
        className={`fixed inset-0 z-40 bg-[#181a20]/20 transition-opacity duration-300 ${
          open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        ref={panelRef}
        id="notification-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`fixed inset-y-0 right-0 z-50 flex w-[380px] max-w-[92vw] flex-col bg-white p-6 shadow-[-16px_0_50px_rgba(24,26,32,0.12)] outline-none transition-transform duration-300 ease-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
        /* 닫혀 있는 동안은 화면 밖이라 탭 순서와 화면 읽기에서 뺀다(inert). aria-hidden을 같이 주면 닫는 순간 초점이 남은
           채로 숨겨져 브라우저가 경고한다 */
        inert={!open}
      >
        <div className="flex items-center justify-between">
          <div>
            <h2 id={titleId} className="text-[20px] font-bold">알림</h2>
            <p className="mt-1 text-[12px] text-[#667085]">
              {readFailed ? "읽음 처리를 저장하지 못했어요. 다시 눌러 주세요." : `읽지 않은 알림 ${unreadNotifications}개`}
            </p>
            <p role="status" className="sr-only">{readNotice}</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              // 누르면 읽지 않은 알림이 0이 되어 disabled가 되고 초점이 빠졌다. 읽을 것이 없으면 aria-disabled로 알리고 누름은 무시한다
              onClick={() => {
                if (unread !== null && unread > 0) void readEverything();
              }}
              aria-disabled={unread === null || unread === 0 || undefined}
              className="text-[12px] font-semibold text-[#4f6ef7] aria-disabled:cursor-default aria-disabled:text-[#a0a4ab]"
            >
              모두 읽음
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex size-9 items-center justify-center rounded-[10px] bg-[#f7f8fa] text-[20px] text-[#667085]"
              aria-label="알림 닫기"
            >
              ×
            </button>
          </div>
        </div>
        <div className="mt-6 flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
          {items.map((notification, index) => (
            <NotificationRow
              key={notification.id}
              notification={notification}
              onOpen={openNotification}
              enterDelay={open ? Math.min(index, LAST_STAGGERED) * 70 : undefined}
            />
          ))}
          {loading && items.length === 0 && (
            <>
              <Skeleton className="h-[76px] rounded-[14px]" />
              <Skeleton className="h-[76px] rounded-[14px]" />
              <Skeleton className="h-[76px] rounded-[14px]" />
            </>
          )}
          {!loading && error !== null && (
            <div className="flex min-h-52 flex-col items-center justify-center gap-2 rounded-[14px] border border-dashed border-[#e5e7eb] px-4 text-center">
              <p className="text-[13px] leading-5 text-[#667085]">{error}</p>
              <button
                type="button"
                // 누르면 이 블록이 사라져 초점이 <body>로 빠지고 Esc도 안 먹는다. 먼저 패널로 초점을 옮긴다
                onClick={() => {
                  panelRef.current?.focus({ preventScroll: true });
                  reload();
                }}
                className="text-[13px] font-semibold text-[#4f6ef7]"
              >
                다시 시도
              </button>
            </div>
          )}
          {!loading && error === null && items.length === 0 && (
            <div className="flex min-h-52 items-center justify-center rounded-[14px] border border-dashed border-[#e5e7eb] text-[14px] font-semibold text-[#667085]">
              새 알림이 없어요
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => {
            onClose();
            navigate({ name: "notifications" });
          }}
          className="mt-4 shrink-0 rounded-[10px] bg-[#f7f8fa] py-3 text-[13px] font-semibold text-[#344054] transition hover:bg-[#eef2ff] hover:text-[#4f6ef7]"
        >
          모든 알림 확인하기
        </button>
      </aside>
    </>
  );
}
