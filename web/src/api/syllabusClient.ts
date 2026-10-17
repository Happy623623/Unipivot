import { ApiError, apiFetch, USE_MOCKS, waitForRun } from "@/api/http";
import { respond, rejectAfter } from "@/api/mockClient";
import { getDevScenario } from "@/dev/scenarios";
import {
  confirmStoredSyllabus,
  extractStoredSyllabus,
  registerStoredSyllabusEvent,
} from "@/mocks/syllabusStore";
import type {
  FileUploadResult,
  SyllabusConfirmItem,
  SyllabusConfirmResult,
  SyllabusExtractResult,
  ProcessStep,
} from "@/types/api";

// 강의계획서 일정 추출·확정 (F-14, API 명세 6·8장). 화면은 client.ts를 거쳐 쓴다.
// 포털 계획서를 PDF로 저장해 올리면(POST /files) 모델이 시험·발표 일정을 뽑고(POST /syllabi/extract),
// 학생이 확인 화면에서 고친 것만 플래너·캘린더로 간다(POST /syllabi/{id}/confirm).

// 추출 실행의 단계 이름(서버의 단계 이름과 같게 둔다). 첫 폴링 전까지 이 이름을 쓴다
export const SYLLABUS_STEPS = ["계획서 글자 읽기", "시험·발표 일정 저장"];

// 추출 결과와 그 실행 번호
export interface SyllabusExtraction {
  run_id: string;
  result: SyllabusExtractResult;
}

const READ_FAILED = "계획서에서 일정을 읽지 못했어요. 포털 계획서를 PDF로 저장해 다시 올려 주세요.";

// 계획서 PDF 올리기 (POST /files, kind=syllabus). 글자가 있는 10쪽 이하 PDF만 받는다
export function uploadSyllabusFile(file: File): Promise<FileUploadResult> {
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
      file_id: `mock-syllabus-${file.size}`,
      kind: "syllabus",
      page_count: 3,
      duplicate_of: null,
      reused: false,
    });
  }
  const form = new FormData();
  form.append("file", file);
  form.append("kind", "syllabus");
  return apiFetch<FileUploadResult>("/files", { method: "POST", body: form });
}

export interface ExtractOptions {
  replace?: boolean; // 이미 계획서가 있는 과목을 갈아 끼운다(409 SYLLABUS_EXISTS 뒤에 다시 부른다)
  onSteps?: (steps: ProcessStep[]) => void;
}

// 올린 계획서에서 일정 뽑기 (POST /syllabi/extract → GET /runs/{id}).
// 실행이 실패하면 서버가 남긴 문구를 그대로 보여 준다(명세 11장)
export async function extractSyllabus(
  fileId: string,
  courseId: string,
  options: ExtractOptions = {},
): Promise<SyllabusExtraction> {
  if (USE_MOCKS) {
    const mocked = extractStoredSyllabus(courseId, options.replace ?? false);
    if (mocked instanceof ApiError) return rejectAfter(mocked);
    // 목 모드는 실행이 없어 단계를 흉내 낸다(화면의 단계 목록이 실제 모드와 같게 보인다)
    SYLLABUS_STEPS.forEach((label, index) =>
      options.onSteps?.(
        SYLLABUS_STEPS.slice(0, index + 1).map((name, seq) => ({
          seq,
          tool: name,
          label: name,
          status: seq === index ? "running" : "succeeded",
          latency_ms: null,
          chosen_by: "pipeline",
          note: null,
        })),
      ),
    );
    return respond(mocked);
  }
  const started = await apiFetch<{ run_id: string }>("/syllabi/extract", {
    method: "POST",
    body: JSON.stringify({
      file_id: fileId,
      lms_course_id: courseId,
      ...(options.replace ? { replace: true } : {}),
    }),
  });
  const run = await waitForRun<SyllabusExtractResult>(started.run_id, (value) =>
    options.onSteps?.(value.steps),
  );
  if (run.status === "failed" || run.result === null) {
    // 4xx로 만들어 서버가 남긴 문구를 그대로 쓴다(5xx면 화면 문구로 바뀐다)
    throw new ApiError(
      run.error?.code ?? "SYLLABUS_READ_FAILED",
      run.error?.message ?? READ_FAILED,
      422,
    );
  }
  return { run_id: started.run_id, result: run.result };
}

// 확인한 일정 저장 (POST /syllabi/{id}/confirm). 고른 것만 플래너·캘린더로 간다.
// 캘린더를 부탁했는데 연결이 없으면 서버가 409 CALENDAR_NOT_CONNECTED이고 아무것도 바뀌지 않는다
export function confirmSyllabus(
  syllabusId: string,
  items: SyllabusConfirmItem[],
  registerCalendar: boolean,
): Promise<SyllabusConfirmResult> {
  if (USE_MOCKS) {
    const result = confirmStoredSyllabus(syllabusId, items, registerCalendar);
    return result instanceof ApiError ? rejectAfter(result) : respond(result);
  }
  return apiFetch<SyllabusConfirmResult>(
    `/syllabi/${encodeURIComponent(syllabusId)}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({
        items,
        register_calendar: registerCalendar,
        ...(registerCalendar ? { calendar_provider: "google" } : {}),
      }),
    },
  );
}

// 확인한 계획서 일정 하나를 Google 캘린더에 넣는다 (POST /calendar/events, 명세 7장).
// 확정할 때 캘린더를 연결하지 않았던 학생이 나중에 넣는 길이다. 두 번 눌러도 일정은 하나다
export function registerSyllabusCalendarEvent(itemId: string): Promise<void> {
  if (USE_MOCKS) {
    registerStoredSyllabusEvent(itemId);
    return respond(undefined);
  }
  return apiFetch<void>("/calendar/events", {
    method: "POST",
    body: JSON.stringify({ provider: "google", syllabus_item_id: itemId }),
  });
}
