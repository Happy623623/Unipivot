import { ApiError } from "@/api/http";
import { getDevScenario } from "@/dev/scenarios";
import { countItems } from "@/lib/feedCounts";
import { courseDetails, courses, lmsUpdates, materials, opportunities } from "@/mocks";
import { mockDepartments, mockNow } from "@/mocks/account";
import { rejudgeStoredOpportunity } from "@/mocks/rejudge";
import { setStoredMark } from "@/mocks/store";
import {
  listStoredNotifications,
  readAllStoredNotifications,
  readStoredNotifications,
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
  Category,
  ConsentResult,
  Course,
  CourseDetail,
  Department,
  FeedResponse,
  IncomeConsentResult,
  LmsConnectResult,
  LmsConnection,
  LmsUpdate,
  MaterialDetail,
  Me,
  NotificationList,
  OpportunityDetail,
  OpportunityMark,
  Profile,
  Settings,
  SyncResponse,
} from "@/types/api";

// 목 모드(NEXT_PUBLIC_USE_MOCKS=true)에서 쓰는 구현 (스킬 mock-to-api).
// 실제 모드 분기가 있는 함수의 목 구현과, 목 함수들이 같이 쓰는 응답 도구를 둔다
const WAIT_MS = 300;

export class MockApiError extends Error {
  constructor(
    public code: "poster_read_failed" | "lms_invalid",
    message: string,
  ) {
    super(message);
  }
}

// 응답이 없는 함수(204처럼 undefined)는 그대로 돌려준다. JSON.parse(undefined)는 오류라 약속이 끝나지 않는다
function clone<T>(value: T): T {
  return value === undefined ? value : (JSON.parse(JSON.stringify(value)) as T);
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

// 목 모드는 cursor·limit를 쓰지 않는다(여섯 건이라 한 쪽에 다 들어간다)
export function getNotifications(unreadOnly: boolean): Promise<NotificationList> {
  return respond(listStoredNotifications(unreadOnly));
}

export function markNotificationsRead(body: { ids: string[] } | { all: true }): Promise<number> {
  if ("all" in body) return respond(readAllStoredNotifications(mockNow));
  return respond(readStoredNotifications(body.ids, mockNow));
}

// 공고 피드·상세 (client.ts)

// 실제 API처럼 관심 없음 공고는 includeNotInterested일 때만 주고, 요약 카드 숫자(카테고리와 상관없는 전체
// 기준)에서는 늘 뺀다
export function getFeed(
  categories: Category[] | null,
  sort: "deadline" | "recent",
  includeNotInterested: boolean,
): Promise<FeedResponse> {
  if (getDevScenario() === "empty_feed") {
    return respond({ items: [], next_cursor: null, counts: countItems([]) });
  }
  const shown = opportunities.filter((item) => item.my_mark !== "not_interested");
  const items = (includeNotInterested ? opportunities : shown).filter((item) => !categories || categories.includes(item.category));
  items.sort((a, b) =>
    sort === "deadline"
      ? (a.d_day ?? Number.MAX_SAFE_INTEGER) - (b.d_day ?? Number.MAX_SAFE_INTEGER)
      : // 실제 API는 등록 최신순이다. 목데이터에는 등록 시각이 없어 새 공고만 앞으로 보낸다
        Number(b.is_new) - Number(a.is_new),
  );
  return respond({ items, next_cursor: null, counts: countItems(shown) });
}

// 정보 입력으로 프로필(목 저장소)이 채워졌으면 그 자리에서 다시 판정한 것처럼 바꿔서 준다
export function getOpportunity(id: string): Promise<OpportunityDetail> {
  const detail = rejudgeStoredOpportunity(id, getStoredProfile());
  if (!detail) return Promise.reject(new Error("공고를 찾을 수 없어요."));
  return respond(detail);
}

// 실제 API처럼 없는 공고에 표시를 붙이면 404 NOT_FOUND이고, 지우기는 늘 된다
export function setOpportunityMark(id: string, mark: OpportunityMark | null): Promise<void> {
  if (!setStoredMark(id, mark) && mark !== null) {
    return rejectAfter(new ApiError("NOT_FOUND", "공고를 찾을 수 없어요.", 404));
  }
  return respond(undefined);
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

export function connectLms(token: string): Promise<LmsConnectResult> {
  const normalized = token.trim();
  if (token !== normalized || normalized.length < 8) {
    return rejectAfter(new MockApiError("lms_invalid", "LearningX 토큰을 확인할 수 없어요."));
  }
  const connection = connectStoredLms(normalized.slice(-4));
  return respond({
    status: "active",
    token_last4: connection.token_last4 ?? normalized.slice(-4),
    courses: courses.length,
    first_sync_run_id: null, // 목 모드는 받아 둔 목데이터가 곧 결과다
  });
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

// 목 모드는 받아 둔 목데이터가 곧 최신이다. 실제 모드와 같은 두 모양을 번갈아 준다 —
// 첫 번째는 "받았다"(화면이 목록을 다시 받는 경로를 목에서도 한 번 돈다), 그 뒤는 "건너뜀"
let syncedOnce = false;

export function syncLms(): Promise<SyncResponse> {
  if (syncedOnce) return respond({ skipped: true, last_synced_at: mockNow });
  syncedOnce = true;
  return respond({ run_id: "mock-sync-run", status: "running" });
}

// 목 모드는 /runs를 부르지 않고 바로 끝난 것으로 친다(목 자료는 이미 최신이다)
export function syncLmsNow(): Promise<boolean> {
  return syncLms().then((started) => "run_id" in started);
}

export function getLmsUpdates(): Promise<LmsUpdate[]> {
  return respond(lmsUpdates);
}

export function getMaterial(fileId: string): Promise<MaterialDetail> {
  const material = materials[fileId];
  if (!material) return Promise.reject(new Error("강의자료를 찾을 수 없어요."));
  return respond(material);
}
