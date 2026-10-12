import { useState } from "react";
import Badge from "@/components/Badge";
import { formatKstDate } from "@/lib/format";
import type { Condition, DetailEligibility, Outcome, UnknownReason } from "@/types/api";
import type { Tone } from "@/types/route";

interface OpportunityConditionsProps {
  eligibility: DetailEligibility;
}

const OUTCOMES: Record<Outcome, { label: string; tone: Tone; mark: string; color: string }> = {
  pass: { label: "충족", tone: "green", mark: "✓", color: "text-[#15803d]" },
  fail: { label: "불충족", tone: "red", mark: "×", color: "text-[#c53030]" },
  unknown: { label: "확인 필요", tone: "yellow", mark: "!", color: "text-[#b7791f]" },
};

// 판정하지 못한 이유별 내 값 자리 문구와, 행을 펼쳤을 때의 안내 (API 명세 5장 unknown_reason)
const UNKNOWN: Record<UnknownReason, { value: string; hint: string }> = {
  missing_profile: { value: "미입력", hint: "정보를 입력하면 바로 다시 판정해요." },
  ambiguous: { value: "원문 확인", hint: "조건이 모호해서 판정하지 않았어요. 원문을 확인해 주세요." },
  unsupported_field: { value: "원문 확인", hint: "프로필로는 판정할 수 없는 조건이에요. 원문을 확인해 주세요." },
  basis_mismatch: { value: "기준 다름", hint: "공고와 내 정보의 기준(실거주·출신 고교 주소, 평점 만점 등)이 달라 직접 확인해야 해요." },
};

// 비어 있어도 같은 묶음의 다른 조건이 충족됐거나 다른 묶음이 불충족이면 정보 입력에서 묻지 않는다
const NOT_ASKED = "입력하지 않은 정보예요. 다른 조건으로 결과가 정해져서 지금은 묻지 않아요.";

function ConditionRow({ condition, asked, open, highlightFailure, onToggle }: {
  condition: Condition;
  asked: boolean; // 정보 입력에서 묻는 항목인지(eligibility.missing_fields)
  open: boolean;
  highlightFailure: boolean;
  onToggle: () => void;
}) {
  const result = OUTCOMES[condition.outcome];
  const unknown = condition.unknown_reason ? UNKNOWN[condition.unknown_reason] : null;
  const hint = condition.unknown_reason === "missing_profile" && !asked ? NOT_ASKED : unknown?.hint;
  const value = condition.user_value_text ?? unknown?.value ?? "미입력";

  return (
    <div className="overflow-hidden rounded-[10px]">
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-center justify-between gap-4 px-1 py-2 text-left">
        <span className="text-[14px] font-medium">
          <b className={`mr-2 ${result.color}`}>{result.mark}</b>
          {condition.label && <span className="mr-1 text-[#667085]">{condition.label}</span>}
          {condition.condition_text}
        </span>
        <span className="flex shrink-0 items-center gap-2 text-[13px] font-semibold">
          <span className={highlightFailure && condition.outcome === "fail" ? "text-[#c53030]" : ""}>{value}</span>
          <Badge tone={result.tone}>{result.label}</Badge>
          <span className="text-[#667085]">{open ? "⌃" : "⌄"}</span>
        </span>
      </button>
      {open && (
        <div className="bg-[#f7f8fa] px-4 py-3 text-[12px] leading-5 text-[#667085]">
          <p>공고 원문: {condition.evidence_text ?? "원문 근거를 확인할 수 없어요."}</p>
          {hint && <p className="mt-1 font-semibold text-[#b7791f]">{hint}</p>}
        </div>
      )}
    </div>
  );
}

// 조건별 판정표. 같은 묶음(clause_no)의 조건은 "다음 중 하나"이고, 묶음끼리는 모두 맞아야 한다
export default function OpportunityConditions({ eligibility }: OpportunityConditionsProps) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const ineligible = eligibility.display_status === "ineligible";
  const groups = eligibility.clauses.map((clause) => ({
    clause,
    rows: eligibility.conditions.filter((condition) => condition.clause_no === clause.clause_no),
  }));
  // 지원 어려움이면 불충족 묶음을 맨 위로 올린다
  const ordered = ineligible
    ? [...groups].sort((a, b) => Number(b.clause.outcome === "fail") - Number(a.clause.outcome === "fail"))
    : groups;

  if (eligibility.conditions.length === 0) {
    return (
      <p className="mt-4 rounded-[10px] bg-[#f7f8fa] px-4 py-3 text-[13px] text-[#344054]">
        {eligibility.display_status === "needs_review"
          ? "공고에서 지원 자격을 정리하지 못했어요. 원문을 확인해 주세요."
          : "공고에 적힌 지원 자격이 없어요."}
      </p>
    );
  }

  const row = (condition: Condition) => (
    <ConditionRow
      key={condition.requirement_id}
      condition={condition}
      asked={eligibility.missing_fields.includes(condition.field)}
      open={expanded === condition.requirement_id}
      highlightFailure={ineligible}
      onToggle={() => setExpanded(expanded === condition.requirement_id ? null : condition.requirement_id)}
    />
  );

  return (
    <div className="mt-4 flex flex-col gap-2">
      {eligibility.basis_date && (
        <p className="text-[12px] text-[#667085]">
          판정 기준일 {formatKstDate(eligibility.basis_date)} · 만 나이·학년·학적은 이날 기준으로 따져요
        </p>
      )}
      {ordered.map(({ clause, rows }) =>
        rows.length < 2 ? (
          rows.map(row)
        ) : (
          <div key={`clause-${clause.clause_no}`} className="rounded-[12px] border border-[#e5e7eb] p-2">
            <div className="flex items-center justify-between px-1 pb-1">
              <span className="text-[12px] font-semibold text-[#667085]">다음 중 하나</span>
              <Badge tone={OUTCOMES[clause.outcome].tone}>{OUTCOMES[clause.outcome].label}</Badge>
            </div>
            {rows.map(row)}
          </div>
        ),
      )}
    </div>
  );
}
