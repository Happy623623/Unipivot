import {
  lmsConnection as initialLmsConnection,
} from "@/mocks/lms";
import {
  me as initialMe,
  profile as initialProfile,
  settings as initialSettings,
} from "@/mocks/account";
import type {
  ConsentResult,
  IncomeConsentResult,
  LmsConnection,
  Me,
  Profile,
  Settings,
} from "@/types/api";

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

const meState = clone(initialMe);
const profileState = clone(initialProfile);
const settingsState = clone(initialSettings);
const lmsState = clone(initialLmsConnection);
// 상태 미리보기 "첫 접속"에서 이번 세션에 동의를 마쳤는지
let consentGiven = false;

export function hasStoredConsent(): boolean {
  return consentGiven;
}

export function storeIncomeConsent(agree: boolean, agreedAt: string): IncomeConsentResult {
  meState.income_info_consented = agree;
  if (!agree) {
    // 서버와 같은 규칙: 동의를 철회하면 소득 3항목을 지운다
    profileState.income_bracket = null;
    profileState.median_income_pct = null;
    profileState.welfare_status = null;
  }
  return { income_info_agreed_at: agree ? agreedAt : null };
}

export function storeConsent(version: string, agreedAt: string, agreeIncomeInfo: boolean): ConsentResult {
  consentGiven = true;
  meState.consented = true;
  const income = storeIncomeConsent(agreeIncomeInfo, agreedAt);
  return {
    terms_agreed_at: agreedAt,
    privacy_agreed_at: agreedAt,
    income_info_agreed_at: income.income_info_agreed_at,
    consent_version: version,
  };
}

export function getStoredMe(): Me {
  return meState;
}

export function getStoredProfile(): Profile {
  return profileState;
}

export function getStoredSettings(): Settings {
  return settingsState;
}

export function getStoredLmsConnection(): LmsConnection {
  return lmsState;
}

export function updateStoredProfile(profile: Profile): Profile {
  Object.assign(profileState, profile);
  meState.profile_completion = {
    filled: Object.values(profileState).filter(
      (value) => value !== null && value !== "",
    ).length,
    total: 15,
  };
  return profileState;
}

export function updateStoredSettings(settings: Settings): Settings {
  Object.assign(settingsState, settings);
  return settingsState;
}

export function disconnectStoredLms(): LmsConnection {
  lmsState.status = "disconnected";
  lmsState.token_last4 = "";
  lmsState.last_synced_at = null;
  lmsState.last_error = null;
  meState.lms = { status: "disconnected", last_synced_at: null };
  return lmsState;
}

export function connectStoredLms(tokenLast4: string): LmsConnection {
  lmsState.status = "active";
  lmsState.token_last4 = tokenLast4;
  lmsState.last_synced_at = "2026-10-05T10:40:00+09:00";
  lmsState.last_error = null;
  meState.lms = {
    status: "active",
    last_synced_at: lmsState.last_synced_at,
  };
  return lmsState;
}

export function reconnectStoredCalendar(): Me {
  meState.calendar_connected = true;
  return meState;
}

export function deleteStoredAccount(): void {
  meState.consented = false;
  consentGiven = false;
  meState.income_info_consented = false;
  meState.lms = null;
  meState.calendar_connected = false;
  Object.keys(profileState).forEach((key) => {
    if (key !== "gpa_scale") {
      profileState[key as keyof Profile] = null as never;
    }
  });
}
