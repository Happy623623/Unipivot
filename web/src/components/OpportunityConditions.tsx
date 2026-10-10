import { useState } from "react";
import Badge from "@/components/Badge";
import type { Condition } from "@/types/api";
import type { Tone } from "@/types/route";

interface OpportunityConditionsProps {
  conditions: Condition[];
  ineligible: boolean;
}

export default function OpportunityConditions({
  conditions,
  ineligible,
}: OpportunityConditionsProps) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const sorted = ineligible
    ? [...conditions].sort((a, b) => Number(b.outcome === "fail") - Number(a.outcome === "fail"))
    : conditions;

  return (
    <div className="mt-4 flex flex-col gap-2">
      {sorted.map((condition) => {
        const result = {
          pass: { label: "충족", tone: "green" as Tone, mark: "✓" },
          fail: { label: "불충족", tone: "red" as Tone, mark: "×" },
          unknown: { label: "확인 필요", tone: "yellow" as Tone, mark: "!" },
        }[condition.outcome];
        const isOpen = expanded === condition.requirement_id;
        const valueIsFailure = ineligible && condition.outcome === "fail";

        return (
          <div key={condition.requirement_id} className="overflow-hidden rounded-[10px]">
            <button
              type="button"
              onClick={() => setExpanded(isOpen ? null : condition.requirement_id)}
              className="flex w-full items-center justify-between gap-4 px-1 py-2 text-left"
            >
              <span className="text-[14px] font-medium">
                <b
                  className={`mr-2 ${
                    condition.outcome === "pass"
                      ? "text-[#15803d]"
                      : condition.outcome === "fail"
                        ? "text-[#c53030]"
                        : "text-[#b7791f]"
                  }`}
                >
                  {result.mark}
                </b>
                {condition.condition_text}
              </span>
              <span className="flex shrink-0 items-center gap-2 text-[13px] font-semibold">
                <span className={valueIsFailure ? "text-[#c53030]" : ""}>
                  {condition.user_value_text ??
                    (condition.field === "other" || condition.is_ambiguous ? "원문 확인" : "미입력")}
                </span>
                <Badge tone={result.tone}>{result.label}</Badge>
                <span className="text-[#667085]">{isOpen ? "⌃" : "⌄"}</span>
              </span>
            </button>
            {isOpen && (
              <p className="bg-[#f7f8fa] px-4 py-3 text-[12px] leading-5 text-[#667085]">
                공고 원문: {condition.evidence_text ?? "원문 근거를 확인할 수 없어요."}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
