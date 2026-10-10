import { useState } from "react";
import Button from "@/components/Button";

export interface ConsentChoice {
  incomeInfo: boolean; // 소득·수급 정보 수집·이용 (선택)
}

interface ConsentStepProps {
  saving: boolean;
  onAgree: (choice: ConsentChoice) => void;
}

type ConsentKey = "terms" | "privacy" | "income";

// TODO(법무): 약관 전문이 확정되면 "보기"에서 전문 페이지로 연결한다
const items: { key: ConsentKey; title: string; required: boolean; summary: string[] }[] = [
  {
    key: "terms",
    title: "이용약관 동의 (필수)",
    required: true,
    summary: [
      "판정 결과는 공고 원문을 대신하지 않아요. 신청 전 원문을 꼭 확인해 주세요.",
      "직접 올린 포스터 공고는 내 피드에만 보여요.",
      "공고 원문·첨부·포스터는 요건을 정리하려고 외부 AI 서비스(LLM API)로 보내요. 내 프로필 값은 보내지 않아요.",
    ],
  },
  {
    key: "privacy",
    title: "개인정보 수집·이용 동의 (필수)",
    required: true,
    summary: [
      "수집 항목: Google 계정 이름·이메일, 직접 입력한 판정용 프로필(소득 정보 제외), 연결한 LMS의 과제·공지 정보",
      "이용 목적: 지원 자격 판정, 준비 일정 생성, 알림",
      "보관 기간: 탈퇴하면 바로 지워요",
    ],
  },
  {
    key: "income",
    title: "소득·수급 정보 수집·이용 동의 (선택)",
    required: false,
    summary: [
      "수집 항목: 학자금 지원구간, 기준 중위소득 %, 기초생활수급·차상위 여부",
      "이용 목적: 소득 기준이 있는 공고의 지원 자격 판정",
      "동의하지 않아도 다른 공고는 그대로 판정해요. 설정에서 언제든 철회할 수 있고, 철회하면 바로 지워요.",
    ],
  },
];

export default function ConsentStep({ saving, onAgree }: ConsentStepProps) {
  const [checked, setChecked] = useState<Record<ConsentKey, boolean>>({ terms: false, privacy: false, income: false });
  const [open, setOpen] = useState<ConsentKey | null>(null);
  const requiredDone = checked.terms && checked.privacy;
  const all = requiredDone && checked.income;

  return (
    <div>
      <h2 className="text-[22px] font-bold">시작하기 전에 동의가 필요해요</h2>
      <p className="mt-1 text-[14px] text-[#667085]">필수 두 항목에 동의하면 공고 판정을 시작할 수 있어요.</p>
      <label className="mt-6 flex cursor-pointer items-center gap-3 rounded-[14px] border border-[#e5e7eb] p-4 text-[15px] font-bold">
        <input
          type="checkbox"
          checked={all}
          onChange={(event) => {
            const value = event.target.checked;
            setChecked({ terms: value, privacy: value, income: value });
          }}
          className="size-4 accent-[#4f6ef7]"
        />
        모두 동의 (선택 포함)
      </label>
      <div className="mt-3 flex flex-col gap-2">
        {items.map((item) => (
          <div key={item.key} className="rounded-[14px] bg-[#f7f8fa] p-4">
            <div className="flex items-center justify-between gap-3">
              <label className="flex cursor-pointer items-center gap-3 text-[14px] font-semibold">
                <input
                  type="checkbox"
                  checked={checked[item.key]}
                  onChange={(event) => setChecked((current) => ({ ...current, [item.key]: event.target.checked }))}
                  className="size-4 accent-[#4f6ef7]"
                />
                {item.title}
              </label>
              <button
                type="button"
                onClick={() => setOpen(open === item.key ? null : item.key)}
                aria-expanded={open === item.key}
                className="shrink-0 text-[13px] font-semibold text-[#4f6ef7]"
              >
                {open === item.key ? "접기" : "보기"}
              </button>
            </div>
            {open === item.key && (
              <ul className="mt-3 list-disc pl-9 text-[12px] leading-5 text-[#667085]">
                {item.summary.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <div className="mt-8 flex justify-end">
        <Button onClick={() => onAgree({ incomeInfo: checked.income })} disabled={!requiredDone || saving}>
          {saving ? "저장 중" : "동의하고 계속"}
        </Button>
      </div>
    </div>
  );
}
