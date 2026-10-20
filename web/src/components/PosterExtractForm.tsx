import { useState } from "react";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import { getCategoryLabel } from "@/lib/format";
import type { Category, PosterExtractResult } from "@/types/api";

interface PosterExtractFormProps {
  result: PosterExtractResult;
  draft: PosterExtractResult["draft"];
  registering: boolean;
  problems: Record<string, string>; // 등록이 422로 막혔을 때 항목별 사유(명세 13장)
  onDraftChange: (draft: PosterExtractResult["draft"]) => void;
  onRegister: () => void;
}

const categories: Category[] = [
  "scholarship",
  "school_program",
  "youth_policy",
  "contest",
  "activity",
  "research",
  "exam",
  "etc",
];

function dateValue(value: string | null): string {
  return value?.slice(0, 10) ?? "";
}

// 날짜만 고쳤을 때 붙이는 시각. 마감은 그날 끝(23:59), 신청 시작은 그날 처음이다(서버 규칙과 같다)
function toDateTime(value: string, endOfDay = false): string | null {
  if (!value) return null;
  return `${value}T${endOfDay ? "23:59" : "00:00"}:00+09:00`;
}

export default function PosterExtractForm({
  result,
  draft,
  registering,
  problems,
  onDraftChange,
  onRegister,
}: PosterExtractFormProps) {
  const [editing, setEditing] = useState(false);
  const isLowConfidence = (field: string) =>
    result.draft.low_confidence_fields.includes(field);
  // 요건·서류는 칸 하나가 아니라 묶음이라 테두리로 강조한다(명세 6장 low_confidence_fields)
  const sectionClass = (field: string) =>
    `mt-5 ${isLowConfidence(field) ? "rounded-[10px] border border-[#b7791f] bg-[#fff8e1] p-3" : ""}`;
  const checkMark = (field: string) =>
    isLowConfidence(field) ? (
      <span className="ml-2 text-[11px] font-normal text-[#b7791f]">확인해 주세요</span>
    ) : null;
  const fieldClass = (field: string) =>
    `rounded-[10px] border p-3 ${
      problems[field]
        ? "border-[#c53030] bg-[#fef2f2]"
        : isLowConfidence(field)
          ? "border-[#b7791f] bg-[#fff8e1]"
          : "border-[#e5e7eb] bg-white"
    }`;
  // 등록이 막힌 사유를 그 칸 아래에 보여 준다. 없으면 확신하지 못한 칸 안내를 그대로 둔다
  const note = (field: string) =>
    problems[field] ? (
      <span className="text-[11px] text-[#c53030]">{problems[field]}</span>
    ) : isLowConfidence(field) ? (
      <span className="text-[11px] text-[#b7791f]">확인해 주세요</span>
    ) : null;

  return (
    <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-[18px] font-semibold">AI 추출 결과 확인</h2>
          <p className="mt-1 text-[12px] text-[#667085]">노란색 항목은 원본과 한 번 더 비교해 주세요.</p>
        </div>
        <Badge tone="green">분석 완료</Badge>
      </div>
      <div className="mt-4 flex flex-col gap-3">
        <label className={fieldClass("title")}>
          <span className="mb-1 block text-[12px] font-medium text-[#667085]">공고명</span>
          <input
            value={draft.title}
            readOnly={!editing}
            onChange={(event) => onDraftChange({ ...draft, title: event.target.value })}
            className="w-full bg-transparent text-[14px] font-semibold outline-none"
          />
          {note("title")}
        </label>
        <label className={fieldClass("organizer")}>
          <span className="mb-1 block text-[12px] font-medium text-[#667085]">주최</span>
          <input
            value={draft.organizer ?? ""}
            readOnly={!editing}
            onChange={(event) => onDraftChange({ ...draft, organizer: event.target.value })}
            className="w-full bg-transparent text-[14px] font-semibold outline-none"
          />
          {note("organizer")}
        </label>
        <label className={fieldClass("category")}>
          <span className="mb-1 block text-[12px] font-medium text-[#667085]">카테고리</span>
          <select
            value={draft.category}
            disabled={!editing}
            onChange={(event) => onDraftChange({ ...draft, category: event.target.value as Category })}
            className="w-full bg-transparent text-[14px] font-semibold outline-none disabled:opacity-100"
          >
            {categories.map((category) => (
              <option key={category} value={category}>{getCategoryLabel(category)}</option>
            ))}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className={fieldClass("apply_start_at")}>
            <span className="mb-1 block text-[12px] font-medium text-[#667085]">신청 시작</span>
            <input
              type="date"
              value={dateValue(draft.apply_start_at)}
              readOnly={!editing}
              onChange={(event) => onDraftChange({ ...draft, apply_start_at: toDateTime(event.target.value) })}
              className="w-full bg-transparent text-[13px] outline-none"
            />
            {note("apply_start_at")}
          </label>
          <label className={fieldClass("deadline_at")}>
            <span className="mb-1 block text-[12px] font-medium text-[#667085]">마감</span>
            <input
              type="date"
              value={dateValue(draft.deadline_at)}
              readOnly={!editing}
              onChange={(event) => onDraftChange({ ...draft, deadline_at: toDateTime(event.target.value, true) })}
              className="w-full bg-transparent text-[13px] outline-none"
            />
            {note("deadline_at")}
          </label>
        </div>
      </div>
      {draft.easy_summary && (
        <div className="mt-5">
          <h3 className="text-[14px] font-semibold">쉬운 설명</h3>
          <p className="mt-2 rounded-[10px] bg-[#f7f8fa] p-3 text-[13px] text-[#344054]">
            {draft.easy_summary}
          </p>
        </div>
      )}
      <div className={sectionClass("requirements")}>
        <h3 className="text-[14px] font-semibold">지원 자격{checkMark("requirements")}</h3>
        <div className="mt-2 flex flex-col gap-2">
          {draft.requirements.map((requirement, index) => (
            <div key={`${requirement.field}-${index}`} className="flex items-center gap-2 rounded-[10px] bg-[#f7f8fa] p-3">
              <input
                value={requirement.condition_text}
                readOnly={!editing}
                onChange={(event) => {
                  const requirements = [...draft.requirements];
                  requirements[index] = { ...requirement, condition_text: event.target.value };
                  onDraftChange({ ...draft, requirements });
                }}
                className="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
              />
              {editing && (
                <button
                  type="button"
                  onClick={() => onDraftChange({ ...draft, requirements: draft.requirements.filter((_, itemIndex) => itemIndex !== index) })}
                  className="text-[12px] font-semibold text-[#c53030]"
                >
                  삭제
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className={sectionClass("documents")}>
        <h3 className="text-[14px] font-semibold">필요 서류{checkMark("documents")}</h3>
        <div className="mt-2 flex flex-wrap gap-2">
          {draft.documents.map((document, index) => (
            <span
              key={`${document.name}-${index}`}
              className="flex items-center gap-2 rounded-full bg-[#f2f4f7] px-3 py-2 text-[12px] font-semibold text-[#475467]"
            >
              {document.name}
              {editing && (
                <button
                  type="button"
                  aria-label={`${document.name} 빼기`}
                  onClick={() => onDraftChange({ ...draft, documents: draft.documents.filter((_, at) => at !== index) })}
                  className="text-[#c53030]"
                >
                  ✕
                </button>
              )}
            </span>
          ))}
        </div>
      </div>
      <p className="mt-5 rounded-[10px] bg-[#eef2ff] p-3 text-[12px] text-[#344054]">
        등록한 포스터 공고는 올린 본인에게만 보여요. 지운 조건은 저장하지 않고, 조건 문장만 고친 것은
        그대로 둬요.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button secondary onClick={() => setEditing((value) => !value)}>
          {editing ? "수정 완료" : "정보 수정"}
        </Button>
        <Button onClick={onRegister} busy={registering}>
          {registering ? "등록 중" : "공고 등록하고 자격 확인"}
        </Button>
      </div>
    </section>
  );
}
