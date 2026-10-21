import { ApiError, apiFetch, notReady, USE_MOCKS, waitForRun } from "@/api/http";
import * as mock from "@/api/mockClient";
import type {
  Course,
  CourseDetail,
  LmsConnectResult,
  LmsConnection,
  LmsUpdate,
  SyncResponse,
} from "@/types/api";

// LMS 연결·동기화·과목·새 소식 (API 명세 9장). 화면은 client.ts를 거쳐 쓴다. 강의자료 요약은 materialsClient.ts

const DISCONNECTED: LmsConnection = {
  status: "disconnected",
  token_last4: null,
  last_synced_at: null,
  last_error: null,
};

// 연결이 없으면 서버가 404 LMS_NOT_CONNECTED를 준다. 화면에는 "연결 안 됨"이 정상 상태다
function asDisconnected(error: unknown): LmsConnection {
  if (error instanceof ApiError && error.code === "LMS_NOT_CONNECTED") return DISCONNECTED;
  throw error;
}

// GET /lms/connection
export function getLmsConnection(): Promise<LmsConnection> {
  if (USE_MOCKS) return mock.getLmsConnection();
  return apiFetch<LmsConnection>("/lms/connection").catch(asDisconnected);
}

// POST /lms/connection. 토큰은 서버로만 보내고 클라이언트에 저장하지 않는다.
// 서버가 수강 과목을 먼저 받아 두고 과제는 첫 동기화로 받는다. 그 동기화까지 기다렸다가
// 끝내야 학업 화면이 "과목은 있는데 과제가 0"으로 보이지 않는다(오래 걸리면 기다리지 않는다)
export async function connectLms(token: string): Promise<LmsConnectResult> {
  if (USE_MOCKS) return mock.connectLms(token);
  const result = await apiFetch<LmsConnectResult>("/lms/connection", {
    method: "POST",
    body: JSON.stringify({ access_token: token }),
  });
  if (result.first_sync_run_id) {
    await waitForRun(result.first_sync_run_id).catch(() => undefined);
  }
  return result;
}

// POST /lms/sync 뒤 결과까지 기다린다. **화면이 목록을 다시 받아야 하면 true**다.
// 마지막 동기화가 5분 안이면 서버가 건너뛰므로(200) 다시 받을 것이 없다.
// 실패했을 때도 true다 — 토큰이 막혔으면 연결 상태가 error로 바뀌어 화면에 알려야 한다
export async function syncLmsNow(): Promise<boolean> {
  if (USE_MOCKS) return mock.syncLmsNow();
  const started = await syncLms().catch(() => null);
  if (started === null) return true;
  if (!("run_id" in started)) return false;
  return (await waitForRun(started.run_id).catch(() => null)) !== null;
}

// DELETE /lms/connection. 토큰만 지우고 과목·과제 기록은 남는다
export async function disconnectLms(): Promise<LmsConnection> {
  if (USE_MOCKS) return mock.disconnectLms();
  await apiFetch<void>("/lms/connection", { method: "DELETE" }).catch(asDisconnected);
  return DISCONNECTED;
}

// POST /lms/sync (F-51). 202면 run_id, 마지막 동기화가 5분 안이면 200 + skipped다.
// 목 모드는 받아 둔 목데이터가 곧 결과라 건너뛴 것으로 친다
export function syncLms(): Promise<SyncResponse> {
  if (USE_MOCKS) return mock.syncLms();
  return apiFetch<SyncResponse>("/lms/sync", { method: "POST" });
}

// GET /lms/courses
export async function getCourses(): Promise<Course[]> {
  if (USE_MOCKS) return mock.getCourses();
  const { items } = await apiFetch<{ items: Course[] }>("/lms/courses");
  return items;
}

// GET /lms/courses/{id}. 부르면 서버가 그 과목을 "봤다"고 적는다(새 자료 수가 줄어든다)
export function getCourse(id: string): Promise<CourseDetail> {
  if (USE_MOCKS) return mock.getCourse(id);
  return apiFetch<CourseDetail>(`/lms/courses/${encodeURIComponent(id)}`);
}

// GET /lms/updates. 최근 14일 새 소식을 처음 본 순으로. 한 쪽(50개)만 쓴다
export async function getLmsUpdates(): Promise<LmsUpdate[]> {
  if (USE_MOCKS) return mock.getLmsUpdates();
  const { items } = await apiFetch<{ items: LmsUpdate[]; next_cursor: string | null }>(
    "/lms/updates",
  );
  return items;
}
