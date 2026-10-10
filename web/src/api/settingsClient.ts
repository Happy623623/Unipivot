import { mockDepartments, mockNow } from "@/mocks/account";
import {
  deleteStoredAccount,
  disconnectStoredLms,
  reconnectStoredCalendar,
  storeConsent,
  storeIncomeConsent,
  updateStoredProfile,
  updateStoredSettings,
} from "@/mocks/accountStore";
import type {
  ConsentResult,
  Department,
  IncomeConsentResult,
  LmsConnection,
  Me,
  Profile,
  Settings,
} from "@/types/api";

const WAIT_MS = 300;

function respond<T>(value: T): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(
      () => resolve(JSON.parse(JSON.stringify(value)) as T),
      WAIT_MS,
    );
  });
}

export function saveProfile(profile: Profile): Promise<Profile> {
  return respond(updateStoredProfile(profile));
}

// POST /me/consents (S1-2에서 실제 API로 교체)
export function saveConsents(version: string, agreeIncomeInfo: boolean): Promise<ConsentResult> {
  return respond(storeConsent(version, mockNow, agreeIncomeInfo));
}

// PATCH /me/consents
export function updateIncomeConsent(agree: boolean): Promise<IncomeConsentResult> {
  return respond(storeIncomeConsent(agree, mockNow));
}

// GET /meta/departments의 items
export function getDepartments(): Promise<Department[]> {
  return respond([...mockDepartments]);
}

export function saveSettings(settings: Settings): Promise<Settings> {
  return respond(updateStoredSettings(settings));
}

export function disconnectLms(): Promise<LmsConnection> {
  return respond(disconnectStoredLms());
}

export function reconnectCalendar(): Promise<Me> {
  return respond(reconnectStoredCalendar());
}

export function deleteAccount(): Promise<void> {
  deleteStoredAccount();
  return new Promise((resolve) => setTimeout(resolve, WAIT_MS));
}
