import { ApiError, apiFetch, USE_MOCKS, waitForRun } from "@/api/http";
import { respond, rejectAfter } from "@/api/mockClient";
import { courseDetails, materials as mockMaterials } from "@/mocks";
import type { FileUploadResult, MaterialDetail, MaterialSummaryResult } from "@/types/api";

// 강의자료 요약(F-15 축소판, API 명세 6·8장). 화면은 client.ts를 거쳐 쓴다.
// 올리기(POST /files, kind=lecture_material) → 요약하기(POST /materials) → 끝나면 GET /materials/{file_id}

// 강의자료를 올리는 곳. 과목 화면은 과목을, 주차 항목 옆 버튼은 그 항목을 붙인다(서버가 내 과목인지 본다)
export interface MaterialPlace {
  courseId?: string;
  moduleItemId?: string;
}

// 목 모드: 올린 자료는 메모리에만 둔다(새로 고치면 처음 목데이터로 돌아간다)
const mockStore = new Map<string, MaterialDetail>(Object.entries(mockMaterials));
const MOCK_SUMMARY = "## 전체 요약\n올린 자료의 핵심을 정리했어요(목 모드).\n## 핵심 개념\n- 개념: 자료에 처음 나온 용어\n## 시험 대비 포인트\n- 정의를 설명할 수 있어야 해요";

export function uploadMaterial(file: File, place: MaterialPlace): Promise<FileUploadResult> {
  if (USE_MOCKS) {
    const fileId = `mock-material-${file.size}`;
    const detail = place.courseId ? courseDetails[place.courseId] : undefined;
    if (detail && !detail.materials.some((one) => one.file_id === fileId)) {
      detail.materials.unshift({ file_id: fileId, original_name: file.name, status: "pending" }); // 과목 상세 목록에도 보인다
    }
    if (!mockStore.has(fileId)) {
      mockStore.set(fileId, {
        file_id: fileId,
        file_name: file.name,
        course: place.courseId ? { lms_course_id: place.courseId, name: "목 과목" } : null,
        source_language: null,
        total_pages: 12,
        processed_range: null,
        status: "pending",
        overall_summary: null,
        over_limit: false,
        run_id: null,
      });
    }
    return respond({ file_id: fileId, kind: "lecture_material", page_count: 12, duplicate_of: null, reused: false });
  }
  const form = new FormData();
  form.append("file", file);
  form.append("kind", "lecture_material");
  if (place.courseId) form.append("lms_course_id", place.courseId);
  if (place.moduleItemId) form.append("lms_module_item_id", place.moduleItemId);
  return apiFetch<FileUploadResult>("/files", { method: "POST", body: form });
}

// GET /materials/{file_id}. 요약을 아직 안 했으면 status가 pending이다
export function getMaterial(fileId: string): Promise<MaterialDetail> {
  if (USE_MOCKS) {
    const found = mockStore.get(fileId);
    return found ? respond(found) : rejectAfter(new ApiError("NOT_FOUND", "강의자료를 찾을 수 없어요. 다시 올려 주세요.", 404));
  }
  return apiFetch<MaterialDetail>(`/materials/${encodeURIComponent(fileId)}`);
}

// POST /materials → 요약이 끝날 때까지 기다린다(이미 요약이 있으면 바로 준다). 상한을 넘으면 413 MATERIAL_TOO_LONG,
// 실행이 실패하면 그 이유(code·message)로 ApiError를 던진다. 1분을 넘기면 RUN_TIMEOUT이다(뒤에서는 계속 돈다)
export async function summarizeMaterial(fileId: string): Promise<MaterialDetail> {
  if (USE_MOCKS) {
    const found = mockStore.get(fileId);
    if (!found) throw new ApiError("NOT_FOUND", "강의자료를 찾을 수 없어요. 다시 올려 주세요.", 404);
    if (found.over_limit) {
      throw new ApiError("MATERIAL_TOO_LONG", "자료가 길어서 한 번에 요약할 수 없어요. 요약할 부분만 PDF로 나눠서 올려 주세요.", 413);
    }
    const done: MaterialDetail = { ...found, status: "succeeded", overall_summary: found.overall_summary ?? MOCK_SUMMARY, processed_range: { start: 1, end: found.total_pages ?? 1 } };
    mockStore.set(fileId, done);
    await new Promise((resolve) => setTimeout(resolve, 800));
    return done;
  }
  const started = await apiFetch<MaterialDetail | { run_id: string; status: "running" }>("/materials", {
    method: "POST",
    body: JSON.stringify({ file_id: fileId }),
  });
  if ("overall_summary" in started) return started; // 이미 요약이 있었다(200)
  let runId = started.run_id;
  // 다른 창이 그새 새 요약을 시작했으면(이 실행의 요약이 아니게 됨) 그 실행도 기다린다
  for (let turn = 0; turn < 3; turn += 1) {
    const run = await waitForRun<MaterialSummaryResult>(runId);
    if (run.status === "failed") {
      // 실행의 실패 문구는 학생에게 보여 줄 말이다(서버가 무엇을 하면 되는지 적었다). 그대로 보이게 상태는 0으로 둔다
      throw new ApiError(run.error?.code ?? "LLM_ERROR", run.error?.message ?? "요약하지 못했어요. 잠시 후 다시 눌러 주세요.", 0);
    }
    const material = await getMaterial(fileId);
    if (material.status !== "running" || !material.run_id || material.run_id === runId) return material;
    runId = material.run_id;
  }
  return getMaterial(fileId);
}
