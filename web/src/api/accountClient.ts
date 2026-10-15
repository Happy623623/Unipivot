import { ApiError, apiFetch, notReady, USE_MOCKS } from "@/api/http";
import * as mock from "@/api/mockClient";
import { connectGoogleCalendar } from "@/lib/googleCalendar";
import type {
  AppNotification,
  ClientEvent,
  ConsentResult,
  Department,
  IncomeConsentResult,
  Me,
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

// 알림 설정(P1)을 보여 줄지. TODO(api): GET·PATCH /me/settings가 생기면 아래 두 함수를 바꾸고 지운다.
// 그 전까지 실제 모드는 설정 화면에서 알림 구역을 숨긴다(목 값이 저장되는 것처럼 보이지 않게)
export const NOTIFICATION_SETTINGS_READY = USE_MOCKS;

export function getSettings(): Promise<Settings> {
  return mock.getSettings();
}

export function saveSettings(settings: Settings): Promise<Settings> {
  return mock.saveSettings(settings);
}

// TODO(api): GET /notifications · POST /notifications/read(10장). 그 전까지 실제 모드는 알림이 없다
export function getNotifications(): Promise<AppNotification[]> {
  return USE_MOCKS ? mock.getNotifications() : Promise.resolve([]);
}

export function markNotificationRead(id: string): Promise<AppNotification[]> {
  return USE_MOCKS ? mock.markNotificationRead(id) : Promise.resolve([]);
}

export function markAllNotificationsRead(): Promise<AppNotification[]> {
  return USE_MOCKS ? mock.markAllNotificationsRead() : Promise.resolve([]);
}

// 탈퇴를 받을지. TODO(api): DELETE /me(4장)가 생기면 deleteAccount를 바꾸고 지운다.
// 그 전까지 실제 모드는 탈퇴 창에서 준비 중이라고 먼저 알린다
export const DELETE_ACCOUNT_READY = USE_MOCKS;

export function deleteAccount(): Promise<void> {
  if (USE_MOCKS) return mock.deleteAccount();
  return notReady("탈퇴는 아직 준비 중이에요. 준비되면 이 화면에서 바로 탈퇴할 수 있어요.");
}
