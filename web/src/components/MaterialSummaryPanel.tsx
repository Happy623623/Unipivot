import { useEffect, useState } from "react";
import { getMaterial } from "@/api/client";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Skeleton from "@/components/Skeleton";
import useAsyncData from "@/lib/useAsyncData";

interface MaterialSummaryPanelProps {
  fileId: string;
  onClose: () => void;
}

export default function MaterialSummaryPanel({
  fileId,
  onClose,
}: MaterialSummaryPanelProps) {
  const request = useAsyncData(() => getMaterial(fileId), [fileId]);
  const [selected, setSelected] = useState<string[]>([]);
  const [translated, setTranslated] = useState<string[]>([]);
  const [translating, setTranslating] = useState(false);
  const [range, setRange] = useState({ start: 1, end: 40 });

  useEffect(() => {
    setSelected([]);
    setTranslated([]);
    setTranslating(false);
  }, [fileId]);

  if (request.loading) return <Skeleton className="h-[520px] rounded-2xl" />;
  if (request.error || !request.data) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "요약을 불러오지 못했어요."}
      </p>
    );
  }

  const material = request.data;
  const translate = () => {
    setTranslating(true);
    setTimeout(() => {
      setTranslated((current) => [...new Set([...current, ...selected])]);
      setTranslating(false);
    }, 800);
  };

  return (
    <aside className="rounded-2xl border border-[#cfd7ff] bg-white p-5">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-[18px] font-semibold">강의자료 요약</h2>
          <p className="mt-1 text-[12px] text-[#667085]">{material.original_name}</p>
        </div>
        <button type="button" onClick={onClose} className="text-[20px] text-[#667085]">×</button>
      </div>
      {material.over_limit && (
        <div className="mt-4 rounded-[10px] bg-[#fff8e1] p-3">
          <p className="text-[12px] font-semibold text-[#b7791f]">
            분량이 많아요. 1–40쪽처럼 범위를 골라 주세요
          </p>
          <div className="mt-3 flex items-center gap-2">
            <input
              type="number"
              min={1}
              max={material.total_pages}
              value={range.start}
              onChange={(event) => setRange({ ...range, start: Number(event.target.value) })}
              className="w-20 rounded-[8px] border border-[#e5e7eb] px-2 py-1 text-[12px]"
            />
            <span>–</span>
            <input
              type="number"
              min={range.start}
              max={material.total_pages}
              value={range.end}
              onChange={(event) => setRange({ ...range, end: Number(event.target.value) })}
              className="w-20 rounded-[8px] border border-[#e5e7eb] px-2 py-1 text-[12px]"
            />
          </div>
        </div>
      )}
      <div className="mt-4 rounded-[12px] bg-[#eef2ff] p-4">
        <p className="text-[13px] font-semibold">전체 요약</p>
        <p className="mt-2 text-[12px] leading-5 text-[#344054]">{material.overall_summary}</p>
      </div>
      <div className="mt-4 flex max-h-[430px] flex-col gap-3 overflow-y-auto">
        {material.sections.map((section) => {
          const isTranslated =
            section.translation_status === "succeeded" ||
            translated.includes(section.id);
          return (
            <article key={section.id} className="rounded-[12px] bg-[#f7f8fa] p-4">
              <div className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={selected.includes(section.id)}
                  onChange={(event) =>
                    setSelected((current) =>
                      event.target.checked
                        ? [...current, section.id]
                        : current.filter((id) => id !== section.id),
                    )
                  }
                  className="mt-1 accent-[#4f6ef7]"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex justify-between gap-3">
                    <p className="text-[13px] font-semibold">{section.title}</p>
                    <span className="shrink-0 text-[11px] text-[#667085]">
                      {section.page_start}–{section.page_end}쪽
                    </span>
                  </div>
                  <p className="mt-2 text-[12px] leading-5 text-[#667085]">{section.summary}</p>
                  {isTranslated && (
                    <a
                      href={section.translation_url ?? "#translation"}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-block text-[12px] font-semibold text-[#4f6ef7]"
                    >
                      번역본 열기
                    </a>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </div>
      <div className="mt-4 flex items-center justify-between">
        {translating && <Badge>번역 중</Badge>}
        <div className="ml-auto">
          <Button onClick={translate} disabled={selected.length === 0 || translating}>
            선택한 구간 번역하기
          </Button>
        </div>
      </div>
    </aside>
  );
}
