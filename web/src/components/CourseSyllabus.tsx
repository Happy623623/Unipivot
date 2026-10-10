import { useState } from "react";
import Button from "@/components/Button";
import { formatKstLongDate } from "@/lib/format";
import type { CourseDetail } from "@/types/api";

interface CourseSyllabusProps {
  course: CourseDetail;
}

const itemLabels = {
  midterm: "중간",
  final: "기말",
  presentation: "발표",
  assignment: "과제",
  etc: "기타",
};

export default function CourseSyllabus({ course }: CourseSyllabusProps) {
  const [uploaded, setUploaded] = useState(false);
  const [toast, setToast] = useState(false);
  const [dates, setDates] = useState<Record<string, string>>(
    Object.fromEntries(
      course.syllabus_items.map((item) => [
        item.id,
        item.starts_at?.slice(0, 10) ?? "",
      ]),
    ),
  );
  const visibleItems = course.course.has_syllabus
    ? course.syllabus_items.filter((item) => item.is_confirmed)
    : course.syllabus_items;

  const schedule = (
    <div className="flex flex-col gap-3">
      {visibleItems.map((item) => (
        <article
          key={item.id}
          className="flex items-center justify-between gap-4 rounded-[12px] bg-[#f7f8fa] p-4"
        >
          <div>
            <p className="text-[12px] font-semibold text-[#4f6ef7]">
              {itemLabels[item.item_type]}
            </p>
            <p className="mt-1 text-[14px] font-semibold">{item.title}</p>
          </div>
          {uploaded ? (
            <input
              type="date"
              value={dates[item.id]}
              onChange={(event) =>
                setDates((current) => ({
                  ...current,
                  [item.id]: event.target.value,
                }))
              }
              className="rounded-[8px] border border-[#e5e7eb] px-2 py-1 text-[12px]"
            />
          ) : (
            <span className="text-[12px] text-[#667085]">
              {item.starts_at
                ? formatKstLongDate(item.starts_at)
                : "일정 미정"}
            </span>
          )}
        </article>
      ))}
    </div>
  );

  if (course.course.has_syllabus) return schedule;

  return (
    <>
      {!uploaded ? (
        <section className="rounded-[14px] border border-dashed border-[#e5e7eb] p-8 text-center">
          <p className="text-[16px] font-semibold">강의계획서를 직접 올려 주세요</p>
          <p className="mt-2 text-[13px] text-[#667085]">
            포털에서 강의계획서 열기 후 PDF로 저장해 올려 주세요
          </p>
          <div className="mt-5 flex justify-center gap-2">
            <a
              href={course.course.portal_syllabus_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-[42px] items-center rounded-[10px] border border-[#e5e7eb] px-[18px] text-[14px] font-semibold"
            >
              포털에서 강의계획서 열기
            </a>
            <label className="inline-flex h-[42px] cursor-pointer items-center rounded-[10px] bg-[#4f6ef7] px-[18px] text-[14px] font-semibold text-white">
              PDF 올리기
              <input
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={(event) =>
                  event.target.files?.[0] && setUploaded(true)
                }
              />
            </label>
          </div>
        </section>
      ) : (
        <>
          <p className="mb-4 text-[13px] text-[#667085]">
            추출된 일정을 확인하고 날짜를 수정해 주세요.
          </p>
          {schedule}
          <div className="mt-4 flex justify-end">
            <Button
              onClick={() => {
                setToast(true);
                setTimeout(() => setToast(false), 2200);
              }}
            >
              확인하고 플래너에 넣기
            </Button>
          </div>
        </>
      )}
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          계획서 일정을 플래너에 넣었어요
        </div>
      )}
    </>
  );
}
