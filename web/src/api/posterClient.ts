import { ApiError, apiFetch, USE_MOCKS, waitForRun } from "@/api/http";
import { respond, rejectAfter } from "@/api/mockClient";
import { getDevScenario } from "@/dev/scenarios";
import { duplicatePosterExtractResult, posterExtractResult } from "@/mocks";
import { MOCK_POSTER_IMAGE, registerStoredPoster } from "@/mocks/posterStore";
import type {
  PosterConfirmResult,
  PosterExtractResult,
  PosterUrl,
  FileUploadResult,
  ProcessStep,
} from "@/types/api";

// 포스터 등록 화면이 쓰는 데이터 함수 (client.ts가 다시 내보낸다).

export type PosterPreviewState =
  | { status: "idle"; result: null }
  | { status: "failure"; result: null }
  | { status: "duplicate"; result: PosterExtractResult };

// 추출 결과와 그 실행 번호. 등록할 때 run_id를 함께 보낸다(서버가 초안을 기준으로 삼는다)
export interface PosterExtraction {
  run_id: string;
  result: PosterExtractResult;
}

// 포스터를 읽는 단계 이름. Vision을 한 번 부르므로 단계도 하나다(서버의 단계 이름과 같게 둔다).
// 실제 모드는 첫 폴링 전까지 이 이름을 쓰고, 그 뒤에는 실행의 처리 과정으로 바꾼다
export const EXTRACT_STEPS = ["포스터에서 글자·날짜 읽기"];

// 목 모드는 실행이 없어 단계를 흉내 낸다("등록 가능"과 다른 뜻이라 따로 둔다)
export const SHOW_MOCK_STEPS = USE_MOCKS;

// 포스터 파일 올리기 (POST /files). 목 모드는 올린 척하고 file_id를 지어낸다
export function uploadPosterFile(file: File): Promise<FileUploadResult> {
  if (USE_MOCKS) {
    if (getDevScenario() === "upload_limit") {
      return rejectAfter(
        new ApiError(
          "DAILY_UPLOAD_LIMIT",
          "오늘 올릴 수 있는 20개를 다 썼어요. 내일 다시 올려 주세요.",
          429,
        ),
      );
    }
    return respond({
      file_id: `mock-file-${file.size}`,
      kind: "poster",
      page_count: null,
      duplicate_of: null,
      reused: false,
    });
  }
  const form = new FormData();
  form.append("file", file);
  form.append("kind", "poster");
  return apiFetch<FileUploadResult>("/files", { method: "POST", body: form });
}

export function getPosterPreviewState(): Promise<PosterPreviewState> {
  const scenario = getDevScenario();
  if (scenario === "poster_failure") return respond({ status: "failure", result: null });
  if (scenario === "poster_duplicate") {
    return respond({ status: "duplicate", result: duplicatePosterExtractResult });
  }
  return respond({ status: "idle", result: null });
}

// 올린 포스터에서 공고 초안 뽑기 (POST /posters/extract → GET /runs/{id}).
// onSteps로 처리 과정을 그때그때 알려 준다(화면의 단계 목록).
export async function extractPoster(
  fileId: string,
  onSteps?: (steps: ProcessStep[]) => void,
): Promise<PosterExtraction> {
  if (USE_MOCKS) return mockExtract();
  const started = await apiFetch<{ run_id: string }>("/posters/extract", {
    method: "POST",
    body: JSON.stringify({ file_id: fileId }),
  });
  const run = await waitForRun<PosterExtractResult>(started.run_id, (value) =>
    onSteps?.(value.steps),
  );
  if (run.status === "failed" || run.result === null) {
    const error = run.error;
    // 실행 실패 이유는 서버가 학생에게 보여 줄 문구로 남긴 것이다(명세 11장). errorMessage가 그 문구를
    // 그대로 쓰도록 4xx로 만든다(5xx면 화면 문구로 바뀐다)
    throw new ApiError(
      error?.code ?? "POSTER_READ_FAILED",
      error?.message ?? "포스터에서 글자를 읽지 못했어요. 다시 찍어서 올려 주세요.",
      422,
    );
  }
  return { run_id: started.run_id, result: run.result };
}

async function mockExtract(): Promise<PosterExtraction> {
  const scenario = getDevScenario();
  if (scenario === "poster_failure") {
    return rejectAfter(
      new ApiError(
        "POSTER_READ_FAILED",
        "포스터에서 글자를 읽지 못했어요. 포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요.",
        422,
      ),
    );
  }
  const result = await respond(
    scenario === "poster_duplicate" ? duplicatePosterExtractResult : posterExtractResult,
  );
  return { run_id: "mock-run", result };
}

// 확인한 내용으로 공고 등록 (POST /posters/confirm). 같은 공고가 이미 있으면 merged가 true다.
// 요건·서류는 서버가 run_id로 추출 초안을 다시 읽어 기준으로 삼고, 지운 줄만 뺀다
export async function registerPosterOpportunity(
  runId: string,
  draft: PosterExtractResult["draft"],
): Promise<PosterConfirmResult> {
  if (USE_MOCKS) {
    const detail = await respond(registerStoredPoster(draft));
    return { opportunity_id: detail.id, merged: false };
  }
  return apiFetch<PosterConfirmResult>("/posters/confirm", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, draft }),
  });
}

// 내가 올린 포스터의 원본을 보는 5분짜리 주소 (GET /opportunities/{id}/poster-url, W6). 원문 보기 창을 열 때마다
// 새로 받고 닫으면 버린다 — 주소는 그 자체로 열쇠라 들고 있지 않는다. 목 모드는 예시 포스터 그림을 준다
export function getPosterUrl(opportunityId: string): Promise<PosterUrl> {
  if (USE_MOCKS) {
    if (getDevScenario() === "poster_gone") {
      return rejectAfter(
        new ApiError("NOT_FOUND", "올린 포스터 파일이 없어졌어요. 포스터를 다시 올려 주세요.", 404),
      );
    }
    return respond({ url: MOCK_POSTER_IMAGE, expires_at: "2026-10-05T09:05:00+09:00" });
  }
  return apiFetch<PosterUrl>(`/opportunities/${encodeURIComponent(opportunityId)}/poster-url`);
}
