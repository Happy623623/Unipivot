import { useState } from "react";
import Badge from "@/components/Badge";
import type { CourseDetail } from "@/types/api";

interface CourseMaterialsProps {
  course: CourseDetail;
  onOpenSummary: (fileId: string) => void;
}

export default function CourseMaterials({
  course,
  onOpenSummary,
}: CourseMaterialsProps) {
  const [uploaded, setUploaded] = useState<Record<string, string>>({});
  const grouped = course.module_items.reduce<
    Record<string, CourseDetail["module_items"]>
  >((groups, item) => {
    groups[item.module_name] = [...(groups[item.module_name] ?? []), item];
    return groups;
  }, {});
  const fallbackFileId = course.materials[0]?.file_id;

  return (
    <div className="flex flex-col gap-5">
      {Object.entries(grouped).map(([moduleName, items]) => (
        <section key={moduleName}>
          <h3 className="text-[15px] font-semibold">{moduleName}</h3>
          <div className="mt-2 flex flex-col gap-2">
            {items?.map((item) => {
              const fileId = item.uploaded_file_id ?? uploaded[item.id];
              return (
                <article
                  key={item.id}
                  className="rounded-[12px] bg-[#f7f8fa] p-4"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-[14px] font-semibold">{item.title}</p>
                        {item.is_new && <Badge>새 자료</Badge>}
                      </div>
                      <p className="mt-1 text-[11px] text-[#667085]">
                        LMS에서 직접 열어야 학습 완료가 인정돼요
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <a
                        href={item.html_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[12px] font-semibold text-[#4f6ef7]"
                      >
                        LMS에서 열기
                      </a>
                      {fileId ? (
                        <button
                          type="button"
                          onClick={() => onOpenSummary(fileId)}
                          className="text-[12px] font-semibold text-[#4f6ef7]"
                        >
                          요약 보기
                        </button>
                      ) : (
                        <label className="cursor-pointer text-[12px] font-semibold text-[#4f6ef7]">
                          받은 PDF 올려서 요약하기
                          <input
                            type="file"
                            accept=".pdf"
                            className="hidden"
                            onChange={(event) => {
                              if (event.target.files?.[0] && fallbackFileId) {
                                setUploaded((current) => ({
                                  ...current,
                                  [item.id]: fallbackFileId,
                                }));
                                onOpenSummary(fallbackFileId);
                              }
                            }}
                          />
                        </label>
                      )}
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
