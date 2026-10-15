import { ApiError, apiFetch, USE_MOCKS, waitForRun } from "@/api/http";
import { respond, rejectAfter } from "@/api/mockClient";
import { getDevScenario } from "@/dev/scenarios";
import { duplicatePosterExtractResult, posterExtractResult } from "@/mocks";
import { registerStoredPoster } from "@/mocks/posterStore";
import type {
  OpportunityDetail,
  PosterExtractResult,
  PosterUploadResult,
  ProcessStep,
} from "@/types/api";

// 포스터 등록 화면이 쓰는 데이터 함수 (client.ts가 다시 내보낸다).

export type PosterPreviewState =
  | { status: "idle"; result: null }
  | { status: "failure"; result: null }
  | { status: "duplicate"; result: PosterExtractResult };

// 확인한 내용으로 공고를 등록할 수 있는지. TODO(api): POST /posters/confirm(W6 3차)이 생기면
// registerPosterOpportunity를 바꾸고 이 값을 지운다. 그 전까지 실제 모드는 확인 화면까지만 간다
export const POSTER_REGISTER_READY = USE_MOCKS;

// 포스터를 읽는 단계 이름. Vision을 한 번 부르므로 단계도 하나다(서버의 단계 이름과 같게 둔다).
// 실제 모드는 첫 폴링 전까지 이 이름을 쓰고, 그 뒤에는 실행의 처리 과정으로 바꾼다
export const EXTRACT_STEPS = ["포스터에서 글자·날짜 읽기"];

// 목 모드는 실행이 없어 단계를 흉내 낸다("등록 가능"과 다른 뜻이라 따로 둔다)
export const SHOW_MOCK_STEPS = USE_MOCKS;

// 포스터 파일 올리기 (POST /files). 목 모드는 올린 척하고 file_id를 지어낸다
export function uploadPosterFile(file: File): Promise<PosterUploadResult> {
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
  return apiFetch<PosterUploadResult>("/files", { method: "POST", body: form });
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
): Promise<PosterExtractResult> {
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
  return run.result;
}

function mockExtract(): Promise<PosterExtractResult> {
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
  return respond(
    scenario === "poster_duplicate" ? duplicatePosterExtractResult : posterExtractResult,
  );
}

// TODO(api): POST /posters/confirm(W6 3차)이 생기면 확인한 draft 등록 요청으로 바꾼다.
export function registerPosterOpportunity(
  draft: PosterExtractResult["draft"],
): Promise<OpportunityDetail> {
  return respond(registerStoredPoster(draft));
}
