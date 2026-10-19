import { getDevScenario } from "@/dev/scenarios";
import { courses } from "@/mocks/lms";
import type { MyFile, MyFileList } from "@/types/api";

// 문서함 목데이터 (F-44). 과목 상세의 공지 첨부(저장됨)·올린 강의자료와 같은 번호를 쓴다 — 공지 탭의 "받기"와
// 문서함이 같은 파일을 가리킨다. 실제 API는 50개씩 주지만 목 모드는 "더 보기"가 보이게 8개씩 나눈다
const MOCK_PAGE = 8;

function courseDocuments(): MyFile[] {
  return courses.flatMap((course, index) => {
    const ref = { id: course.id, short_name: course.short_name, is_active: true };
    const items: MyFile[] = [
      {
        file_id: `${course.id}-n2-file`,
        file_name: "중간고사 대비 예제.pdf",
        kind: "lecture_material",
        origin: "lms_attachment",
        course: ref,
        size_bytes: 1_843_200,
        created_at: `2026-10-04T16:${String(10 - index).padStart(2, "0")}:00+09:00`,
      },
      {
        file_id: `${course.id}-material`,
        file_name: `${course.short_name}_8주차.pdf`,
        kind: "lecture_material",
        origin: "upload",
        course: ref,
        size_bytes: 3_276_800 + index * 524_288,
        created_at: `2026-10-02T2${index}:30:00+09:00`,
      },
    ];
    if (course.has_syllabus) {
      items.push({
        file_id: `${course.id}-syllabus-file`,
        file_name: `${course.short_name} 강의계획서.pdf`,
        kind: "syllabus",
        origin: "upload",
        course: ref,
        size_bytes: 245_760,
        created_at: `2026-09-0${index + 2}T10:00:00+09:00`,
      });
    }
    return items;
  });
}

// 지난 학기 과목의 공지 첨부. 수강이 끝나 과목 화면은 열리지 않는다(문서함은 "과목 보기"를 숨긴다)
const pastAttachment: MyFile = {
  file_id: "past-course-file",
  file_name: "기말 대비 정리.pdf",
  kind: "lecture_material",
  origin: "lms_attachment",
  course: { id: "past-course", short_name: "자료구조", is_active: false },
  size_bytes: 2_097_152,
  created_at: "2026-06-10T15:00:00+09:00",
};

// 오늘 올리고 아직 과목을 고르지 않은 계획서(과목을 모른다). 가장 최근 파일이어도 묶음은 맨 아래다
const looseSyllabus: MyFile = {
  file_id: "loose-syllabus-file",
  file_name: "교양 강의계획서.pdf",
  kind: "syllabus",
  origin: "upload",
  course: null,
  size_bytes: 198_656,
  created_at: "2026-10-05T08:30:00+09:00",
};

const documents = [...courseDocuments(), pastAttachment, looseSyllabus].sort((a, b) =>
  b.created_at.localeCompare(a.created_at),
);

// GET /files 흉내. cursor는 다음 쪽의 시작 순번이다. LMS를 연결하지 않은 상태 미리보기는 빈 문서함이다
export function mockDocumentPage(cursor: string | null): MyFileList {
  const all = getDevScenario() === "lms_disconnected" ? [] : documents;
  const start = cursor ? Number(cursor) : 0;
  const end = start + MOCK_PAGE;
  return { items: all.slice(start, end), next_cursor: end < all.length ? String(end) : null };
}

export function findMockDocument(fileId: string): MyFile | undefined {
  return documents.find((item) => item.file_id === fileId);
}

// 목 모드에서 받는 한 쪽짜리 PDF(글자만). 오프셋 표(xref)를 맞춰 PDF 보기 프로그램에서도 열린다
export function mockPdf(): string {
  const stream = "BT /F1 18 Tf 72 760 Td (UNIPIVOT mock document) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = objects.map((body, index) => {
    const offset = pdf.length;
    pdf += `${index + 1} 0 obj\n${body}\nendobj\n`;
    return offset;
  });
  const table = offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  const size = objects.length + 1;
  return `${pdf}xref\n0 ${size}\n0000000000 65535 f \n${table}trailer\n<< /Size ${size} /Root 1 0 R >>\nstartxref\n${pdf.length}\n%%EOF\n`;
}
