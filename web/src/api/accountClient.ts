import { ApiError, apiFetch, USE_MOCKS } from "@/api/http";
import * as mock from "@/api/mockClient";
import { removePushSubscription } from "@/api/pushClient";
import { connectGoogleCalendar } from "@/lib/googleCalendar";
import { unsubscribeIfAny } from "@/lib/push";
import { createBrowserSupabase, hasStoredSession } from "@/lib/supabase/client";
import type {
  ClientEvent,
  ConsentResult,
  Department,
  IncomeConsentResult,
  Me,
  NotificationList,
  NotificationReadResult,
  Profile,
  ProfileUpdateResponse,
  Settings,
} from "@/types/api";

// 내 정보·프로필·동의·학과·캘린더 연결·사용 기록·설정·알림·탈퇴 (API 명세 4·10장).
// 화면은 client.ts를 거쳐 쓴다. 목 모드면 mockClient.ts, 아니면 FastAPI를 부른다

// GET /me
export function getMe(): Promise<Me> {
  return USE_MOCKS ? mock.getMe() : apiFetch<Me>("/me");
}

// GET /me/profile
export function getProfile(): Promise<Profile> {
  return USE_MOCKS ? mock.getProfile() : apiFetch<Profile>("/me/profile");
}

// PATCH /me/profile. 화면은 프로필 전체를 보낸다. 서버는 바뀐 항목만 저장하고 공고를 다시 판정한다
export async function saveProfile(profile: Profile): Promise<Profile> {
  if (USE_MOCKS) return mock.saveProfile(profile);
  const result = await apiFetch<ProfileUpdateResponse>("/me/profile", {
    method: "PATCH",
    body: JSON.stringify(profile),
  });
  return result.profile;
}

// POST /me/consents (온보딩 동의 단계). 필수 두 항목은 화면이 체크해야 부른다
export function saveConsents(version: string, agreeIncomeInfo: boolean): Promise<ConsentResult> {
  if (USE_MOCKS) return mock.saveConsents(version, agreeIncomeInfo);
  return apiFetch<ConsentResult>("/me/consents", {
    method: "POST",
    body: JSON.stringify({
      consent_version: version,
      agree_terms: true,
      agree_privacy: true,
      agree_income_info: agreeIncomeInfo,
    }),
  });
}

// PATCH /me/consents. 끄면 서버가 소득 3항목을 지우고 다시 판정한다
export function updateIncomeConsent(agree: boolean): Promise<IncomeConsentResult> {
  if (USE_MOCKS) return mock.updateIncomeConsent(agree);
  return apiFetch<IncomeConsentResult>("/me/consents", {
    method: "PATCH",
    body: JSON.stringify({ agree_income_info: agree }),
  });
}

// GET /meta/departments의 items
export async function getDepartments(): Promise<Department[]> {
  if (USE_MOCKS) return mock.getDepartments();
  const { items } = await apiFetch<{ items: Department[] }>("/meta/departments");
  return items;
}

// 설정의 캘린더 연결. 실제 모드는 API를 부르지 않고 Google 화면으로 떠난다(증분 승인, API 4장).
// 콜백이 토큰을 저장한 뒤 /settings?calendar=connected(또는 error)로 돌아온다
export async function reconnectCalendar(): Promise<Me> {
  if (USE_MOCKS) return mock.reconnectCalendar();
  const error = await connectGoogleCalendar("/settings");
  if (error) throw new ApiError("CALENDAR_CONNECT_FAILED", error, 0);
  return new Promise<Me>(() => {}); // 페이지가 Google로 넘어가므로 끝나지 않는다
}

// DELETE /auth/google/tokens (F-06). Google 쪽 권한을 거두고 저장한 토큰을 지운다. 이미 넣은 일정은
// 캘린더에 그대로 남는다. 연결이 없어도 204라 두 번 눌러도 같다. 바뀐 내 정보는 다시 받는다
export async function disconnectCalendar(): Promise<Me> {
  if (USE_MOCKS) return mock.disconnectCalendar();
  await apiFetch<void>("/auth/google/tokens", { method: "DELETE" });
  return getMe();
}

// 설정 밖(공고 상세의 "캘린더에 넣기")에서 캘린더 권한을 받으러 갈 때. 끝나면 next로 돌아온다.
// 목 모드는 Google로 가지 않고 그 자리에서 연결한 것으로 친다(부르는 쪽이 이어서 등록한다)
export async function connectCalendar(next: string): Promise<void> {
  if (USE_MOCKS) {
    await mock.reconnectCalendar();
    return;
  }
  const error = await connectGoogleCalendar(next);
  if (error) throw new ApiError("CALENDAR_CONNECT_FAILED", error, 0);
  return new Promise<void>(() => {}); // 페이지가 Google로 넘어가므로 끝나지 않는다
}

// POST /events. 기록용이라 기다리지 않고, 실패해도 화면은 그대로 둔다 (API 4장)
export function recordEvent(event: ClientEvent, opportunityId?: string): void {
  if (USE_MOCKS) return;
  apiFetch<void>("/events", {
    method: "POST",
    body: JSON.stringify(opportunityId ? { event, opportunity_id: opportunityId } : { event }),
  }).catch(() => undefined);
}

// GET /me/settings. 바꾼 적이 없으면 서버가 기본값을 준다(푸시 켬·끈 종류 없음·자동 등록 켬)
export function getSettings(): Promise<Settings> {
  return USE_MOCKS ? mock.getSettings() : apiFetch<Settings>("/me/settings");
}

// PATCH /me/settings. 화면은 설정 전체를 보내고 서버는 받은 항목만 바꾼다
export function saveSettings(settings: Settings): Promise<Settings> {
  if (USE_MOCKS) return mock.saveSettings(settings);
  return apiFetch<Settings>("/me/settings", {
    method: "PATCH",
    body: JSON.stringify(settings),
  });
}

// 알림함 한 쪽에 담는 알림 수. 서버 최대값은 50이다(API 명세 10장)
export const NOTIFICATION_PAGE_SIZE = 20;

export interface NotificationParams {
  unreadOnly?: boolean;
  limit?: number;
  cursor?: string | null;
}

// GET /notifications (10장). 보낼 때가 지난 알림만 최신순으로 오고, unread_count는 필터와 상관없이 전체 기준이다.
// cursor는 unread_only가 같은 목록에서만 쓸 수 있어 다르면 422다(부르는 쪽이 처음부터 다시 받는다)
export function getNotifications(params: NotificationParams = {}): Promise<NotificationList> {
  if (USE_MOCKS) return mock.getNotifications(Boolean(params.unreadOnly));
  const query = new URLSearchParams({ limit: String(params.limit ?? NOTIFICATION_PAGE_SIZE) });
  if (params.unreadOnly) query.set("unread_only", "true");
  if (params.cursor) query.set("cursor", params.cursor);
  return apiFetch<NotificationList>(`/notifications?${query}`);
}

// POST /notifications/read. 새 안 읽은 수를 돌려준다(헤더 배지에 쓴다)
export function markNotificationRead(id: string): Promise<number> {
  return readNotifications({ ids: [id] });
}

export function markAllNotificationsRead(): Promise<number> {
  return readNotifications({ all: true });
}

async function readNotifications(body: { ids: string[] } | { all: true }): Promise<number> {
  if (USE_MOCKS) return mock.markNotificationsRead(body);
  const result = await apiFetch<NotificationReadResult>("/notifications/read", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return result.unread_count;
}

// 시간이 걸리는 정리를 기다리되 로그아웃이 멈추지 않게 끝을 둔다
function within<T>(work: Promise<T>, ms: number): Promise<T | undefined> {
  return Promise.race([work, new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), ms))]);
}

// 로그아웃 (F-06). 이 기기의 세션만 끝낸다 — scope "local"이면 Supabase가 이 세션의 갱신 토큰을 거두고 브라우저 쿠키를
// 지운다(다른 기기의 로그인은 그대로). 이미 받은 접근 토큰은 만료(1시간)까지 남는다.
// 1) 먼저 이 브라우저의 웹 푸시 구독을 지우고 서버에도 알린다(토큰이 살아 있을 때) — 안 그러면 로그아웃한 기기로
//    알림이 계속 간다(명세 10장). 실패해도 넘어간다(브라우저 구독이 없으면 서버는 보낼 때 410으로 스스로 지운다).
// 2) Supabase 로그아웃. 서버에 알리지 못해도 supabase-js는 이 기기의 세션을 먼저 지운다. 다만 세션을 불러오다(만료된
//    토큰 갱신) 실패하면 지우지 않고 오류만 돌려주므로, 세션 쿠키가 남았으면 던져서 그 자리에서 다시 누르게 한다(8초까지 기다린다).
// 3) 로그인 화면으로 간다. 뒤로 가기로 개인 정보가 그려진 설정 화면이 돌아오지 않게 기록을 바꾼다(replace).
// 목 모드는 서버가 없어 1)·3)만 한다
export async function signOut(): Promise<void> {
  try {
    const endpoint = await within(unsubscribeIfAny(), 3000);
    if (endpoint) await within(removePushSubscription(endpoint), 3000);
  } catch {
    // 푸시 정리 실패로 로그아웃을 막지 않는다
  }
  if (!USE_MOCKS) {
    // 연결이 끊기면 supabase-js가 갱신을 몇 번 다시 해 보느라 25초쯤 걸린다. 8초만 기다리고 세션이 남았으면 알린다
    // (그 뒤에 끝나도 다시 누르면 세션이 없어 바로 로그인 화면으로 간다)
    await within(createBrowserSupabase().auth.signOut({ scope: "local" }), 8000);
    if (hasStoredSession()) throw new Error("세션이 남았어요");
  }
  window.location.replace("/login?notice=signed_out");
  return new Promise<void>(() => {}); // 페이지가 바뀌므로 끝나지 않는다
}

// DELETE /me (4장, F-06). 서버가 파일·Google 권한·프로필을 지운다. 끝나면 이 기기의 세션을 지우고
// 로그인 화면으로 간다(로그인 계정은 남아, 다시 로그인하면 동의부터 새로 시작한다).
// 목 모드는 그 자리에서 동의 전 상태로 돌아간다(부르는 쪽이 온보딩으로 보낸다)
export async function deleteAccount(): Promise<void> {
  if (USE_MOCKS) return mock.deleteAccount();
  await apiFetch<void>("/me", { method: "DELETE" });
  await createBrowserSupabase().auth.signOut({ scope: "local" });
  window.location.replace("/login?notice=deleted"); // 뒤로 가기로 지운 계정의 화면이 돌아오지 않게
  return new Promise<void>(() => {}); // 페이지가 바뀌므로 끝나지 않는다
}
