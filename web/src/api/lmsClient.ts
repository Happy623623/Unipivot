import { notReady, USE_MOCKS } from "@/api/http";
import * as mock from "@/api/mockClient";
import type { Course, CourseDetail, LmsConnection, LmsUpdate, MaterialDetail } from "@/types/api";

// LMS 연결·과목·새 소식·강의자료 (API 명세 8·9장). 화면은 client.ts를 거쳐 쓴다.
// TODO(api): LMS API(9장)가 생기면 안쪽을 apiFetch로 바꾸고 LMS_CONNECT_READY를 지운다.
// 그 전까지 실제 모드는 "연결 안 됨"으로 보이고, 연결·과목 상세·강의자료는 준비 중 오류를 준다

// LMS 연결을 권할지. false면 온보딩 끝의 LMS 단계를 건너뛰고, 연결 창은 준비 중 안내만 보여 준다
export const LMS_CONNECT_READY = USE_MOCKS;

const LMS_NOT_READY = "LMS 연결은 아직 준비 중이에요.";

export function getLmsConnection(): Promise<LmsConnection> {
  if (USE_MOCKS) return mock.getLmsConnection();
  return Promise.resolve({ status: "disconnected", token_last4: "", last_synced_at: null, last_error: null });
}

// 실제 API는 토큰을 서버로만 보내고 클라이언트에는 저장하지 않는다
export function connectLms(token: string): Promise<LmsConnection> {
  return USE_MOCKS ? mock.connectLms(token) : notReady(LMS_NOT_READY);
}

export function disconnectLms(): Promise<LmsConnection> {
  return USE_MOCKS ? mock.disconnectLms() : notReady(LMS_NOT_READY);
}

export function getCourses(): Promise<Course[]> {
  return USE_MOCKS ? mock.getCourses() : Promise.resolve([]);
}

export function getCourse(id: string): Promise<CourseDetail> {
  return USE_MOCKS ? mock.getCourse(id) : notReady(LMS_NOT_READY);
}

export function getLmsUpdates(): Promise<LmsUpdate[]> {
  return USE_MOCKS ? mock.getLmsUpdates() : Promise.resolve([]);
}

export function getMaterial(fileId: string): Promise<MaterialDetail> {
  return USE_MOCKS ? mock.getMaterial(fileId) : notReady("강의자료 요약은 아직 준비 중이에요.");
}
