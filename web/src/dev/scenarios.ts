export type DevScenario =
  | "default"
  | "first_visit"
  | "lms_disconnected"
  | "lms_error"
  | "calendar_expired"
  | "empty_feed"
  | "poster_failure"
  | "poster_duplicate"
  | "upload_limit";

let currentScenario: DevScenario = "default";

export function getDevScenario(): DevScenario {
  return currentScenario;
}

export function setDevScenario(scenario: DevScenario): void {
  currentScenario = scenario;
}

export const scenarioLabels: Record<DevScenario, string> = {
  default: "기본",
  first_visit: "첫 접속(동의 전)",
  lms_disconnected: "LMS 미연결",
  lms_error: "LMS 오류",
  calendar_expired: "캘린더 만료",
  empty_feed: "빈 피드",
  poster_failure: "포스터 분석 실패",
  poster_duplicate: "포스터 중복",
  upload_limit: "업로드 한도 초과",
};
