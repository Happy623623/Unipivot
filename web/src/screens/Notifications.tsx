import { useEffect, useState } from "react";
import { todayKst } from "@/api/client";
import { useAppShell } from "@/components/AppShell";
import Button from "@/components/Button";
import Header from "@/components/Header";
import { EmptyBox } from "@/components/HomeStates";
import NotificationRow from "@/components/NotificationRow";
import PushEnableBanner from "@/components/PushEnableBanner";
import Skeleton from "@/components/Skeleton";
import Toast from "@/components/Toast";
import { formatKstLongDate, getKstDateKey } from "@/lib/format";
import notificationRoute from "@/lib/notificationRoute";
import useNotifications from "@/lib/useNotifications";
import useToast from "@/lib/useToast";
import type { AppNotification } from "@/types/api";
import type { Route } from "@/types/route";

// 알림함 전체 목록 (F-35). 헤더 패널의 "모든 알림 확인하기"로 들어온다.
// 알림을 누르면 읽음 처리하고 그 화면으로 가고, 쪽은 cursor로 이어 받는다(API 명세 10장)
interface DayGroup {
  key: string;
  label: string;
  items: AppNotification[];
}

function shiftDay(dateKey: string, days: number): string {
  return getKstDateKey(new Date(new Date(`${dateKey}T00:00:00+09:00`).getTime() + days * 86_400_000));
}

function dayLabel(dateKey: string, today: string): string {
  if (dateKey === today) return "오늘";
  if (dateKey === shiftDay(today, -1)) return "어제";
  return formatKstLongDate(dateKey);
}

// 받은 순서(최신순)대로 같은 날끼리 묶는다
function dayGroups(items: AppNotification[], today: string): DayGroup[] {
  const groups: DayGroup[] = [];
  items.forEach((item) => {
    const key = getKstDateKey(item.scheduled_at);
    const last = groups.at(-1);
    if (last?.key === key) last.items.push(item);
    else groups.push({ key, label: dayLabel(key, today), items: [item] });
  });
  return groups;
}

const tabs: { label: string; unreadOnly: boolean }[] = [
  { label: "전체", unreadOnly: false },
  { label: "안 읽은 알림", unreadOnly: true },
];

export default function Notifications({ navigate }: { navigate: (route: Route) => void }) {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const { unreadNotifications, setUnreadNotifications } = useAppShell();
  const [toast, showToast] = useToast();
  const { items, unread, loading, error, hasMore, loadingMore, reload, loadMore, read, readAll } =
    useNotifications({ unreadOnly });

  useEffect(() => {
    if (unread !== null) setUnreadNotifications(unread);
  }, [unread, setUnreadNotifications]);

  const openNotification = async (notification: AppNotification) => {
    const route = notificationRoute(notification);
    if (route) {
      void read(notification);
      navigate(route);
      return;
    }
    // 갈 곳이 없는 알림은 그 자리에 남아 있어 실패를 알려 줄 수 있다
    if (!(await read(notification))) showToast("읽음 처리를 저장하지 못했어요. 다시 눌러 주세요.");
  };

  const readEverything = async () => {
    if (await readAll()) showToast("알림을 모두 읽음으로 바꿨어요.");
    else showToast("읽음 처리를 저장하지 못했어요. 다시 눌러 주세요.");
  };

  const groups = dayGroups(items, todayKst());
  return (
    <>
      <Header
        title="알림"
        subtitle={
          unreadNotifications > 0 ? `읽지 않은 알림 ${unreadNotifications}개` : "읽지 않은 알림이 없어요"
        }
      />
      <PushEnableBanner onDone={showToast} />
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <div role="group" aria-label="알림 목록" className="flex items-baseline gap-4">
          {tabs.map((tab) => (
            <button
              key={tab.label}
              type="button"
              onClick={() => setUnreadOnly(tab.unreadOnly)}
              aria-pressed={unreadOnly === tab.unreadOnly}
              className={`text-[20px] font-semibold transition-colors ${
                unreadOnly === tab.unreadOnly
                  ? "text-[#181a20]"
                  : "text-[#a0a4ab] hover:text-[#667085]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={readEverything}
          disabled={unread === null || unread === 0}
          className="text-[13px] font-semibold text-[#4f6ef7] disabled:cursor-default disabled:text-[#a0a4ab]"
        >
          모두 읽음
        </button>
      </div>
      {loading && items.length === 0 && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-5 w-20" />
          <Skeleton className="h-[76px] rounded-[14px]" />
          <Skeleton className="h-[76px] rounded-[14px]" />
          <Skeleton className="h-[76px] rounded-[14px]" />
        </div>
      )}
      {!loading && error !== null && items.length === 0 && (
        <EmptyBox title={error} action="다시 시도" onAction={reload} />
      )}
      {!loading && error === null && items.length === 0 && !unreadOnly && (
        <EmptyBox
          title="아직 받은 알림이 없어요"
          action="공고 보기"
          onAction={() => navigate({ name: "home" })}
        />
      )}
      {!loading && error === null && items.length === 0 && unreadOnly && (
        <EmptyBox title="안 읽은 알림이 없어요" action="전체 알림 보기" onAction={() => setUnreadOnly(false)} />
      )}
      {groups.map((group) => (
        <section key={group.key} className="flex flex-col gap-2">
          <h2 className="text-[13px] font-semibold text-[#667085]">{group.label}</h2>
          {group.items.map((notification) => (
            <NotificationRow
              key={notification.id}
              notification={notification}
              onOpen={openNotification}
            />
          ))}
        </section>
      ))}
      {error !== null && items.length > 0 && (
        <p className="text-[13px] text-[#c53030]">{error}</p>
      )}
      {hasMore && (
        <div className="flex justify-center">
          <Button secondary onClick={loadMore} disabled={loadingMore}>
            {loadingMore ? "불러오는 중…" : "더 보기"}
          </Button>
        </div>
      )}
      <Toast toast={toast} />
    </>
  );
}
