import { createBrowserSupabase } from "@/lib/supabase/client";
import type { Run } from "@/types/api";

// 실제 FastAPI 호출 (API 명세 1·2·13장). 화면은 이 파일을 직접 쓰지 않고 client.ts 함수만 쓴다.
// code는 서버가 준 13장 코드를 그대로 쓴다. 서버에 닿지 못한 경우만 프론트 코드를 쓴다:
// NETWORK_ERROR(서버 연결 실패), CONFIG_MISSING(API 주소 없음), NOT_READY(아직 API가 없는 기능),
// CALENDAR_CONNECT_FAILED(Google 화면을 열지 못함), RUN_TIMEOUT(실행 확인 시간 초과),
// DOWNLOAD_FAILED(받기 주소에서 파일을 받지 못함, documentsClient.ts)
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

// 목 모드면 목데이터, 아니면 FastAPI
export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "true";

// 실제 모드에서 아직 API가 없는 기능은 목데이터 대신 빈 값이나 이 오류를 준다
export function notReady(message: string): Promise<never> {
  return Promise.reject(new ApiError("NOT_READY", message, 0));
}

const FALLBACK_MESSAGE = "요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.";

// 응답을 받지 못했다. 기기가 오프라인이면 인터넷을, 아니면 서버(꺼짐·주소·CORS 설정)를 탓한다
function networkMessage(): string {
  return typeof navigator !== "undefined" && !navigator.onLine
    ? "인터넷에 연결되어 있지 않아요. 연결을 확인하고 다시 시도해 주세요."
    : "서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.";
}

// 응답을 받기까지. 로그인 전·세션 만료(401)면 로그인 화면으로 보내고 끝나지 않는 Promise를 둔다
async function apiResponse(path: string, init: RequestInit = {}): Promise<Response> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base) {
    throw new ApiError("CONFIG_MISSING", "API 주소(NEXT_PUBLIC_API_BASE_URL)가 설정되지 않았어요.", 0);
  }
  const { data } = await createBrowserSupabase().auth.getSession();
  const token = data.session?.access_token;
  // 파일 업로드(multipart)는 Content-Type을 브라우저가 경계 문자열과 함께 붙인다. 우리가 넣으면 깨진다
  const isForm = init.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      ...init,
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError("NETWORK_ERROR", networkMessage(), 0);
  }
  // 로그인 전이면 로그인 화면으로, 세션이 만료됐으면 이유와 함께 보낸다.
  // 페이지가 바뀌므로 화면에 오류를 넘기지 않고 기다리게 둔다
  if (response.status === 401 && typeof window !== "undefined") {
    window.location.assign(token ? "/login?error=session" : "/login");
    return new Promise<Response>(() => {});
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.error?.code ?? "UNKNOWN",
      body?.error?.message ?? FALLBACK_MESSAGE,
      response.status,
      body?.error?.details,
    );
  }
  return response;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiResponse(path, init);
  return (response.status === 204 ? undefined : await response.json()) as T;
}

// JSON이 아닌 응답(.ics 파일 같은 글)을 그대로 받는다
export async function apiFetchText(path: string): Promise<string> {
  return (await apiResponse(path)).text();
}

// 화면에 띄울 오류 문구. 서버(13장)와 프론트 코드가 준 문구는 그대로 쓰고,
// 서버 내부 오류(5xx)·알 수 없는 오류·목 모드 오류는 화면이 준 문구를 쓴다
export function errorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError) || error.status >= 500 || error.code === "UNKNOWN") return fallback;
  return error.message;
}

const HANGUL = /[가-힣]/;

// 422 VALIDATION_FAILED의 details.fields를 항목별 문구로. 서버가 준 한국어 문구는 그대로 쓰고,
// 요청 형식 검사에서 온 영어 문구는 "값을 확인해 주세요."로 바꾼다
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.code !== "VALIDATION_FAILED") return {};
  const fields = error.details?.fields;
  if (!fields || typeof fields !== "object") return {};
  return Object.fromEntries(
    Object.entries(fields as Record<string, unknown>).map(([key, message]) => [
      key,
      typeof message === "string" && HANGUL.test(message) ? message : "값을 확인해 주세요.",
    ]),
  );
}

// 403 CONSENT_REQUIRED의 details.consent: terms_privacy(필수 동의 전) · income_info(소득 선택 동의 전)
export function consentRequired(error: unknown): "terms_privacy" | "income_info" | null {
  if (!(error instanceof ApiError) || error.code !== "CONSENT_REQUIRED") return null;
  const consent = error.details?.consent;
  return consent === "terms_privacy" || consent === "income_info" ? consent : null;
}

// 202로 받은 run_id를 1.5초 간격으로 최대 60초까지 확인한다 (API 2장)
export async function waitForRun<R>(runId: string, onProgress?: (run: Run<R>) => void): Promise<Run<R>> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < 60_000) {
    const run = await apiFetch<Run<R>>(`/runs/${runId}`);
    onProgress?.(run);
    if (run.status === "succeeded" || run.status === "failed") return run;
    await new Promise((resolve) => setTimeout(resolve, 1_500));
  }
  throw new ApiError("RUN_TIMEOUT", "백그라운드에서 계속 처리하고 있어요. 끝나면 알림으로 알려드릴게요.", 0);
}
