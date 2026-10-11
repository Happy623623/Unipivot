import { getDevScenario } from "@/dev/scenarios";
import { courseDetails, courses, lmsUpdates, materials } from "@/mocks";
import { mockDepartments, mockNow } from "@/mocks/account";
import {
  getStoredNotifications,
  readAllStoredNotifications,
  readStoredNotification,
} from "@/mocks/notificationStore";
import {
  connectStoredLms,
  deleteStoredAccount,
  disconnectStoredLms,
  getStoredLmsConnection,
  getStoredMe,
  getStoredProfile,
  getStoredSettings,
  hasStoredConsent,
  reconnectStoredCalendar,
  storeConsent,
  storeIncomeConsent,
  updateStoredProfile,
  updateStoredSettings,
} from "@/mocks/accountStore";
import type {
  AppNotification,
  ConsentResult,
  Course,
  CourseDetail,
  Department,
  IncomeConsentResult,
  LmsConnection,
  LmsUpdate,
  MaterialDetail,
  Me,
  Profile,
  Settings,
} from "@/types/api";

// 목 모드(NEXT_PUBLIC_USE_MOCKS=true)에서 쓰는 구현 (스킬 mock-to-api).
// 실제 모드 분기가 있는 함수의 목 구현과, 목 함수들이 같이 쓰는 응답 도구를 둔다
const WAIT_MS = 300;

export class MockApiError extends Error {
  constructor(
    public code: "poster_read_failed" | "upload_limit" | "lms_invalid",
    message: string,
  ) {
    super(message);
  }
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function respond<T>(value: T): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(clone(value)), WAIT_MS);
  });
}

export function rejectAfter(error: Error): Promise<never> {
  return new Promise((_, reject) => {
    setTimeout(() => reject(error), WAIT_MS);
  });
}

// 내 정보·프로필·동의·학과·캘린더·설정·알림·탈퇴 (accountClient.ts)

export function getMe(): Promise<Me> {
  const scenario = getDevScenario();
  const result = clone(getStoredMe());

  if (scenario === "first_visit" && !hasStoredConsent()) {
    result.consented = false;
    result.income_info_consented = false;
  }
  if (scenario === "lms_disconnected") {
    result.lms = { status: "disconnected", last_synced_at: null };
  }
  if (scenario === "lms_error" && result.lms) result.lms.status = "error";
  if (scenario === "calendar_expired") result.calendar_connected = false;

  return respond(result);
}

export function getProfile(): Promise<Profile> {
  return respond(getStoredProfile());
}

export function saveProfile(profile: Profile): Promise<Profile> {
  return respond(updateStoredProfile(profile));
}

export function saveConsents(version: string, agreeIncomeInfo: boolean): Promise<ConsentResult> {
  return respond(storeConsent(version, mockNow, agreeIncomeInfo));
}

export function updateIncomeConsent(agree: boolean): Promise<IncomeConsentResult> {
  return respond(storeIncomeConsent(agree, mockNow));
}

export function getDepartments(): Promise<Department[]> {
  return respond([...mockDepartments]);
}

export function reconnectCalendar(): Promise<Me> {
  return respond(reconnectStoredCalendar());
}

export function getSettings(): Promise<Settings> {
  return respond(getStoredSettings());
}

export function saveSettings(settings: Settings): Promise<Settings> {
  return respond(updateStoredSettings(settings));
}

export function deleteAccount(): Promise<void> {
  deleteStoredAccount();
  return new Promise((resolve) => setTimeout(resolve, WAIT_MS));
}

export function getNotifications(): Promise<AppNotification[]> {
  return respond(getStoredNotifications());
}

export function markNotificationRead(id: string): Promise<AppNotification[]> {
  return respond(readStoredNotification(id, mockNow));
}

export function markAllNotificationsRead(): Promise<AppNotification[]> {
  return respond(readAllStoredNotifications(mockNow));
}

// LMS (lmsClient.ts)

export function getLmsConnection(): Promise<LmsConnection> {
  const scenario = getDevScenario();
  const result = clone(getStoredLmsConnection());
  if (scenario === "lms_disconnected") {
    result.status = "disconnected";
    result.last_synced_at = null;
  }
  if (scenario === "lms_error") {
    result.status = "error";
    result.last_error = "LearningX 인증 정보가 만료됐어요. 다시 연결해 주세요.";
  }
  return respond(result);
}

export function connectLms(token: string): Promise<LmsConnection> {
  const normalized = token.trim();
  if (token !== normalized || normalized.length < 8) {
    return rejectAfter(new MockApiError("lms_invalid", "LearningX 토큰을 확인할 수 없어요."));
  }
  return respond(connectStoredLms(normalized.slice(-4)));
}

export function disconnectLms(): Promise<LmsConnection> {
  return respond(disconnectStoredLms());
}

export function getCourses(): Promise<Course[]> {
  return respond(courses);
}

export function getCourse(id: string): Promise<CourseDetail> {
  const course = courseDetails[id];
  if (!course) return Promise.reject(new Error("과목을 찾을 수 없어요."));
  return respond(course);
}

export function getLmsUpdates(): Promise<LmsUpdate[]> {
  return respond(lmsUpdates);
}

export function getMaterial(fileId: string): Promise<MaterialDetail> {
  const material = materials[fileId];
  if (!material) return Promise.reject(new Error("강의자료를 찾을 수 없어요."));
  return respond(material);
}
