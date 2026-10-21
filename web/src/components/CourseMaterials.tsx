import { useRef, useState, type ChangeEvent } from "react";
import { errorMessage, uploadMaterial, type MaterialPlace } from "@/api/client";
import Badge from "@/components/Badge";
import { AI_NOTICE } from "@/components/MaterialSummaryPanel";
import type { CourseDetail, RunStatus } from "@/types/api";

const NO_WEEK = "주차 미정";
const UPLOAD_FAILED = "강의자료를 올리지 못했어요. 잠시 후 다시 올려 주세요.";
const STATUS_LABEL: Record<RunStatus, string> = {
  pending: "요약 전",
  running: "요약 중",
  succeeded: "요약 완료",
  failed: "요약 못 함",
};

interface CourseMaterialsProps {
  course: CourseDetail;
  onOpenSummary: (fileId: string) => void;
  onUploaded: () => void; // 올린 자료가 목록·주차 항목에 보이도록 과목 상세를 다시 받는다
}

// 과목 상세의 자료 탭(F-52·F-15). LMS 주차 자료는 LMS에서 열어야 학습 완료가 인정돼서 바로가기만 두고,
// 받은 PDF를 올리면 요약한다. 주차 항목 옆에서 올리면 그 항목에 붙는다(새 자료 알림과 같은 자리)
export default function CourseMaterials({ course, onOpenSummary, onUploaded }: CourseMaterialsProps) {
  const [uploading, setUploading] = useState<string | null>(null); // 올리는 중인 자리(과목 "course" 또는 주차 항목 id)
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const place = useRef<{ key: string; value: MaterialPlace } | null>(null);
  const grouped = course.module_items.reduce<Record<string, CourseDetail["module_items"]>>((groups, item) => {
    const week = item.module_name ?? NO_WEEK; // 주차 이름이 없는 항목도 있다
    groups[week] = [...(groups[week] ?? []), item];
    return groups;
  }, {});

  const pick = (key: string, value: MaterialPlace) => {
    if (uploading) return; // 하나씩 올린다(누름은 aria-disabled로만 막는다)
    place.current = { key, value };
    input.current?.click();
  };

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ""; // 같은 파일을 다시 골라도 change가 오게
    const target = place.current;
    if (!file || !target) return;
    setUploading(target.key);
    setError(null);
    try {
      const saved = await uploadMaterial(file, target.value);
      onUploaded();
      onOpenSummary(saved.file_id); // 요약 창이 열리자마자 요약한다
    } catch (caught) {
      setError(errorMessage(caught, UPLOAD_FAILED));
    } finally {
      setUploading(null);
    }
  };

  const uploadButton = (key: string, value: MaterialPlace, label: string) => (
    <button
      type="button"
      onClick={() => pick(key, value)}
      aria-disabled={uploading !== null}
      aria-busy={uploading === key}
      className="text-[12px] font-semibold text-[#4f6ef7] aria-disabled:text-[#a0a4ab]"
    >
      {uploading === key ? "올리는 중" : label}
    </button>
  );

  return (
    <div className="flex flex-col gap-5">
      <input ref={input} type="file" accept="application/pdf,.pdf" className="hidden" onChange={upload} aria-hidden tabIndex={-1} />
      <section className="rounded-[12px] border border-[#e5e7eb] p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-[15px] font-semibold">내가 올린 강의자료</h3>
            <p className="mt-1 text-[12px] text-[#667085]">글자가 있는 PDF를 올리면 한 번에 요약해요. 스캔한 자료는 아직 요약하지 못해요.</p>
          </div>
          {uploadButton("course", { courseId: course.course.id }, "PDF 올려서 요약하기")}
        </div>
        <p className="mt-2 text-[11px] text-[#667085]">{AI_NOTICE}</p>
        {error && <p role="status" className="mt-3 rounded-[10px] bg-[#fef2f2] px-3 py-2 text-[12px] text-[#c53030]">{error}</p>}
        {course.materials.length > 0 && (
          <ul className="mt-3 flex flex-col gap-2">
            {course.materials.map((material) => (
              <li key={material.file_id} className="flex items-center justify-between gap-3 rounded-[10px] bg-[#f7f8fa] px-3 py-2">
                <span className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-[13px] font-medium">{material.original_name ?? "강의자료"}</span>
                  <Badge tone={material.status === "succeeded" ? "green" : material.status === "failed" ? "yellow" : "gray"}>
                    {STATUS_LABEL[material.status]}
                  </Badge>
                </span>
                <button type="button" onClick={() => onOpenSummary(material.file_id)} className="shrink-0 text-[12px] font-semibold text-[#4f6ef7]">
                  요약 보기
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      {Object.entries(grouped).map(([moduleName, items]) => (
        <section key={moduleName}>
          <h3 className="text-[15px] font-semibold">{moduleName}</h3>
          <div className="mt-2 flex flex-col gap-2">
            {items?.map((item) => (
              <article key={item.id} className="rounded-[12px] bg-[#f7f8fa] p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-[14px] font-semibold">{item.title}</p>
                      {item.is_new && <Badge>새 자료</Badge>}
                    </div>
                    <p className="mt-1 text-[11px] text-[#667085]">LMS에서 직접 열어야 학습 완료가 인정돼요</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    {item.html_url && (
                      <a href={item.html_url} target="_blank" rel="noreferrer" className="text-[12px] font-semibold text-[#4f6ef7]">
                        LMS에서 열기
                      </a>
                    )}
                    {item.uploaded_file_id ? (
                      <button type="button" onClick={() => onOpenSummary(item.uploaded_file_id as string)} className="text-[12px] font-semibold text-[#4f6ef7]">
                        요약 보기
                      </button>
                    ) : (
                      uploadButton(item.id, { courseId: course.course.id, moduleItemId: item.id }, "받은 PDF 올려서 요약하기")
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
