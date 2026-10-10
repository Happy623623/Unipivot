import { useState } from "react";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import { getCategoryLabel } from "@/lib/format";
import type { Category, PosterExtractResult } from "@/types/api";

interface PosterExtractFormProps {
  result: PosterExtractResult;
  draft: PosterExtractResult["draft"];
  registering: boolean;
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

function toDateTime(value: string): string | null {
  return value ? `${value}T09:00:00+09:00` : null;
}

export default function PosterExtractForm({
  result,
  draft,
  registering,
  onDraftChange,
  onRegister,
}: PosterExtractFormProps) {
  const [editing, setEditing] = useState(false);
  const isLowConfidence = (field: string) =>
    result.draft.low_confidence_fields.includes(field);
  const fieldClass = (field: string) =>
    `rounded-[10px] border p-3 ${
      isLowConfidence(field)
        ? "border-[#b7791f] bg-[#fff8e1]"
        : "border-[#e5e7eb] bg-white"
    }`;

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
          {isLowConfidence("title") && <span className="text-[11px] text-[#b7791f]">확인해 주세요</span>}
        </label>
        <label className={fieldClass("organizer")}>
          <span className="mb-1 block text-[12px] font-medium text-[#667085]">주최</span>
          <input
            value={draft.organizer ?? ""}
            readOnly={!editing}
            onChange={(event) => onDraftChange({ ...draft, organizer: event.target.value })}
            className="w-full bg-transparent text-[14px] font-semibold outline-none"
          />
          {isLowConfidence("organizer") && <span className="text-[11px] text-[#b7791f]">확인해 주세요</span>}
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
            {isLowConfidence("apply_start_at") && <span className="text-[11px] text-[#b7791f]">확인해 주세요</span>}
          </label>
          <label className={fieldClass("deadline_at")}>
            <span className="mb-1 block text-[12px] font-medium text-[#667085]">마감</span>
            <input
              type="date"
              value={dateValue(draft.deadline_at)}
              readOnly={!editing}
              onChange={(event) => onDraftChange({ ...draft, deadline_at: toDateTime(event.target.value) })}
              className="w-full bg-transparent text-[13px] outline-none"
            />
            {isLowConfidence("deadline_at") && <span className="text-[11px] text-[#b7791f]">확인해 주세요</span>}
          </label>
        </div>
      </div>
      <div className="mt-5">
        <h3 className="text-[14px] font-semibold">지원 자격</h3>
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
      <div className="mt-5">
        <h3 className="text-[14px] font-semibold">필요 서류</h3>
        <div className="mt-2 flex flex-wrap gap-2">
          {draft.documents.map((document, index) => (
            <input
              key={`${document.name}-${index}`}
              value={document.name}
              readOnly={!editing}
              onChange={(event) => {
                const documents = [...draft.documents];
                documents[index] = { ...document, name: event.target.value };
                onDraftChange({ ...draft, documents });
              }}
              className="rounded-full bg-[#f2f4f7] px-3 py-2 text-[12px] font-semibold text-[#475467] outline-none"
            />
          ))}
        </div>
      </div>
      <p className="mt-5 rounded-[10px] bg-[#eef2ff] p-3 text-[12px] text-[#344054]">
        등록하면 다른 학생 피드에도 공개되고, 이름은 김*지처럼 가려져요.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button secondary onClick={() => setEditing((value) => !value)}>
          {editing ? "수정 완료" : "정보 수정"}
        </Button>
        <Button onClick={onRegister} disabled={registering}>
          {registering ? "등록 중" : "공고 등록하고 자격 확인"}
        </Button>
      </div>
    </section>
  );
}
