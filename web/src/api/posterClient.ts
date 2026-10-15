import { ApiError, apiFetch, USE_MOCKS } from "@/api/http";
import { MockApiError, rejectAfter, respond } from "@/api/mockClient";
import { getDevScenario } from "@/dev/scenarios";
import { duplicatePosterExtractResult, posterExtractResult } from "@/mocks";
import { registerStoredPoster } from "@/mocks/posterStore";
import type { OpportunityDetail, PosterExtractResult, PosterUploadResult } from "@/types/api";

// 포스터 등록 화면이 쓰는 데이터 함수 (client.ts가 다시 내보낸다).

export type PosterPreviewState =
  | { status: "idle"; result: null }
  | { status: "failure"; result: null }
  | { status: "duplicate"; result: PosterExtractResult };

// 올린 포스터에서 공고를 뽑아낼 수 있는지. TODO(api): POST /posters/extract·/posters/confirm(W6 2차)가
// 생기면 아래 extractPoster·registerPosterOpportunity를 바꾸고 이 값을 지운다. 그 전까지 실제 모드는
// 파일을 올리는 데까지만 하고 자동 정리는 준비 중이라고 알린다(목 공고는 실제 상세에서 열리지 않는다)
export const POSTER_EXTRACT_READY = USE_MOCKS;

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

// TODO(api): 포스터 추출 run 생성 API와 연결되면 올린 file_id를 전달한다.
export function extractPoster(_fileId: string): Promise<PosterExtractResult> {
  const scenario = getDevScenario();
  if (scenario === "poster_failure") {
    return rejectAfter(
      new MockApiError("poster_read_failed", "포스터에서 글자를 읽지 못했어요."),
    );
  }
  return respond(
    scenario === "poster_duplicate"
      ? duplicatePosterExtractResult
      : posterExtractResult,
  );
}

// TODO(api): 실제 공고 등록 API가 확정되면 draft 등록 요청으로 교체한다.
export function registerPosterOpportunity(
  draft: PosterExtractResult["draft"],
): Promise<OpportunityDetail> {
  return respond(registerStoredPoster(draft));
}
