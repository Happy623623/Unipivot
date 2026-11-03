import { ApiError, apiFetch, USE_MOCKS, waitForRun } from "@/api/http";
import { rejectAfter, respond } from "@/api/mockClient";
import { getDevScenario } from "@/dev/scenarios";
import type { NoticeLinkResult, NoticeLinkStarted, ProcessStep } from "@/types/api";

// 학교 공지 링크로 공고 가져오기(B안, API 명세 6장 POST /notices/link). 공고 등록 화면이 쓴다(client.ts가 다시 내보낸다).
// 학생이 붙인 한양대 공지 한 건만 서버가 그 자리에서 읽는다. 가져온 공지는 학교 공지라 모든 학생에게 보인다

// 서버의 단계 이름과 같게 둔다(app/schemas/notices.py). 첫 폴링 전에는 이 이름을, 그 뒤에는 실행의 단계를 보여 준다
export const NOTICE_LINK_STEPS = ["공지 페이지 읽기", "첨부 파일 받기", "AI로 지원 자격 정리"];
export const SHOW_MOCK_NOTICE_STEPS = USE_MOCKS;
// 학교 사이트를 읽고 첨부까지 정리해서 포스터보다 오래 걸릴 수 있다. 그래도 넘으면 "아직 정리 중"으로 안내한다
const WAIT_MS = 150_000;
const FAILED = "공지를 가져오지 못했어요. 잠시 후 다시 붙여 주세요.";
// 목 모드에서 열어 줄 학교 공지(목데이터에 있는 공고)
const MOCK_NOTICE_ID = "hanyang-support-2026";

export interface NoticeLinkOutcome {
  opportunity_id: string;
  // new: 새로 가져왔다. 나머지는 이미 있던 공지다(누가 먼저 가져왔다)
  status: NoticeLinkResult["status"];
}

// 공지 링크 한 건 가져오기 (POST /notices/link → GET /runs/{id}). onSteps로 처리 과정을 그때그때 알려 준다
export async function importNoticeLink(
  url: string,
  onSteps?: (steps: ProcessStep[]) => void,
): Promise<NoticeLinkOutcome> {
  if (USE_MOCKS) return mockImport(url);
  const started = await apiFetch<NoticeLinkStarted>("/notices/link", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
  if (started.status === "existing" && started.opportunity_id) {
    return { opportunity_id: started.opportunity_id, status: "existing" };
  }
  if (!started.run_id) throw new ApiError("NOTICE_FETCH_FAILED", FAILED, 422);
  const run = await waitForRun<NoticeLinkResult>(started.run_id, (value) => onSteps?.(value.steps), WAIT_MS);
  if (run.status === "failed" || run.result === null) {
    // 실패 이유는 서버가 학생에게 보여 줄 문구로 남긴 것이다(명세 11장). errorMessage가 그대로 쓰게 4xx로 만든다
    throw new ApiError(run.error?.code ?? "NOTICE_FETCH_FAILED", run.error?.message ?? FAILED, 422);
  }
  return { opportunity_id: run.result.opportunity_id, status: run.result.status };
}

// 목 모드: 서버처럼 한양대 공지 글 주소만 받고, 목데이터의 학교 공지를 연다
async function mockImport(url: string): Promise<NoticeLinkOutcome> {
  const scenario = getDevScenario();
  if (scenario === "notice_link_limit") {
    return rejectAfter(
      new ApiError("DAILY_LINK_LIMIT", "오늘 가져올 수 있는 10개를 다 썼어요. 내일 다시 붙여 주세요.", 429),
    );
  }
  let host = "";
  try {
    host = new URL(url.includes("://") ? url.trim() : `https://${url.trim()}`).hostname;
  } catch {
    host = "";
  }
  if (host !== "www.hanyang.ac.kr" && host !== "hanyang.ac.kr") {
    return rejectAfter(
      new ApiError("VALIDATION_FAILED", "입력값을 확인해 주세요.", 422, {
        fields: { url: "한양대 공지사항(www.hanyang.ac.kr)의 글 주소만 가져올 수 있어요." },
      }),
    );
  }
  if (scenario === "notice_link_failure") {
    return rejectAfter(
      new ApiError("NOTICE_FETCH_FAILED", "학교 사이트에서 공지를 읽지 못했어요. 잠시 후 다시 붙여 주세요.", 422),
    );
  }
  return respond({ opportunity_id: MOCK_NOTICE_ID, status: "new" as const });
}
