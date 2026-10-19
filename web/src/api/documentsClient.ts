import { ApiError, apiFetch, USE_MOCKS } from "@/api/http";
import { rejectAfter, respond } from "@/api/mockClient";
import { DownloadFailed, fetchDownload, saveTextFile } from "@/lib/saveFile";
import { findMockDocument, mockDocumentPage, mockPdf } from "@/mocks/documents";
import type { FileDownloadUrl, MyFileList } from "@/types/api";

// 문서함 (F-44, API 명세 6장). 화면은 client.ts를 거쳐 쓴다.

const PAGE_SIZE = 50; // API 최대값. 한 학기 자료는 보통 한 쪽에 다 들어온다

// GET /files. 내 강의자료(공지 첨부 포함)·강의계획서를 최신순으로. 다음 쪽은 앞 응답의 next_cursor로 받는다
export function getDocuments(cursor: string | null = null): Promise<MyFileList> {
  if (USE_MOCKS) return respond(mockDocumentPage(cursor));
  const query = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (cursor) query.set("cursor", cursor);
  return apiFetch<MyFileList>(`/files?${query}`);
}

// 파일 하나를 `fileName`으로 내려받는다. 누를 때마다 5분짜리 받기 주소(GET /files/{id}/url)를 새로 받아 바로
// 그 주소에서 파일을 받는다(fetch) — 주소는 그 자체로 열쇠라 들고 있지 않는다. 저장소가 파일을 주지 않으면
// 프론트 코드 DOWNLOAD_FAILED(13장)로, 안내 문구는 그대로 화면에 간다. 목 모드는 한 쪽짜리 예시 PDF를 같은 이름으로 준다
export async function downloadDocument(fileId: string, fileName: string): Promise<void> {
  if (USE_MOCKS) {
    const found = findMockDocument(fileId);
    if (!found) return rejectAfter(new ApiError("NOT_FOUND", "파일을 찾을 수 없어요.", 404));
    await respond(null);
    saveTextFile(fileName, mockPdf(), "application/pdf");
    return;
  }
  const { url } = await apiFetch<FileDownloadUrl>(`/files/${encodeURIComponent(fileId)}/url`);
  try {
    await fetchDownload(url, fileName);
  } catch (error) {
    if (error instanceof DownloadFailed) throw new ApiError("DOWNLOAD_FAILED", error.message, 0);
    throw error;
  }
}
