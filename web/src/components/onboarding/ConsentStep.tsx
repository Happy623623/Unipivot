import { useRef, useState } from "react";
import Link from "next/link";
import Button from "@/components/Button";

export interface ConsentChoice {
  incomeInfo: boolean; // 소득·수급 정보 수집·이용 (선택)
}

interface ConsentStepProps {
  saving: boolean;
  onAgree: (choice: ConsentChoice) => void;
  // 이미 동의한 사람에게 바뀐 약관을 다시 물을 때(lib/consent.ts). incomeOn: 지금 소득·수급 동의가 켜져 있는지
  renewal?: { incomeOn: boolean };
}

type ConsentKey = "age" | "terms" | "privacy" | "income";

// 문구를 바꾸면 lib/consent.ts의 CONSENT_VERSION을 올리고 아래 바뀐 점을 고친다(이미 동의한 사람에게 다시 묻는다).
// 개인정보 두 항목은 "보기" 안에서 처리방침 전문(/privacy)을 새 탭으로 연다 — 같은 탭이면 고르던 동의가 사라진다.
// TODO(법무): 이용약관 전문이 확정되면 그 항목에도 전문 링크를 단다
const PRIVACY_POLICY = "/privacy";
const items: { key: ConsentKey; title: string; required: boolean; summary: string[]; fullText?: string }[] = [
  {
    key: "age",
    title: "만 14세 이상이에요 (필수)",
    required: true,
    summary: ["만 14세 미만은 법정대리인 동의가 필요해서 UNIPIVOT을 쓸 수 없어요."],
  },
  {
    key: "terms",
    title: "이용약관 동의 (필수)",
    required: true,
    summary: [
      "판정 결과는 공고 원문을 대신하지 않아요. 신청 전 원문을 꼭 확인해 주세요.",
      "직접 올린 포스터 공고는 내 피드에만 보여요.",
      "공고 원문·첨부·포스터는 요건을 정리하려고, 준비하기의 서류 안내를 만들 때는 공고 제목·주최·서류 이름(청년정책은 제출 서류 안내 글)을 외부 AI 서비스(Google Gemini)로 보내요.",
      "LearningX를 연결하면 과목 공지의 제목·본문을 분류·요약하고 공고면 요건을 정리하려고, 강의계획서·강의자료를 올리거나 공지 첨부를 요약하면 그 파일을 일정을 뽑고 요약하려고 같은 서비스로 보내요.",
      "내 프로필 값(성적·소득 등)은 외부 AI로 보내지 않아요.",
    ],
  },
  {
    key: "privacy",
    title: "개인정보 수집·이용 동의 (필수)",
    required: true,
    summary: [
      "수집 항목: Google 계정(이름·이메일·프로필 사진·계정 번호), 직접 입력한 판정용 프로필(소득 정보 제외), 동의 기록, 이용 기록(판정 결과·관심·준비 일정·알림·앱을 연 날 같은 이용 이벤트), AI 처리 기록, 접속 기록(IP·브라우저)",
      "켜거나 올릴 때만: LearningX 토큰과 과목·과제·공지·주차 자료, 올린 파일(포스터·강의계획서·강의자료), Google 캘린더 권한, 웹 푸시 구독",
      "이용 목적: 회원 식별, 지원 자격 판정, 공고 요건 정리, 준비 일정 생성, 과제·공지 알림, 캘린더 등록, 강의자료 요약, 오류 확인·보안, 서비스 개선과 성능·비용 측정",
      "보관 기간: 탈퇴할 때까지예요. 탈퇴하면 바로 지우고, 처리 기록처럼 누구 것인지 지운 채 남는 것은 처리방침 3장에 적었어요.",
      "동의하지 않으면 UNIPIVOT을 쓸 수 없어요.",
    ],
    fullText: PRIVACY_POLICY,
  },
  {
    key: "income",
    title: "소득·수급 정보 수집·이용 동의 (선택)",
    required: false,
    summary: [
      "수집 항목: 학자금 지원구간, 기준 중위소득 %, 본인 연 소득, 기초생활수급·차상위 여부",
      "이용 목적: 소득 기준이 있는 공고의 지원 자격 판정",
      "동의하지 않아도 다른 공고는 그대로 판정해요. 설정에서 언제든 철회할 수 있고, 철회하면 바로 지워요.",
    ],
    fullText: PRIVACY_POLICY,
  },
];

// 다시 물을 때 보여 주는 바뀐 점(지난 버전 2026-10-07과 견줘)
const CONSENT_CHANGES = [
  "동의 문구에 빠져 있던 것을 처리방침(10/28)에 맞춰 채웠어요. 이번에 새로 시작하는 처리는 없어요.",
  "외부 AI(Google Gemini)로 보내는 자료에 LearningX 과목 공지, 올린 강의계획서·강의자료, 요약한 공지 첨부, 서류 안내에 쓰는 공고 정보를 적었어요.",
  "개인정보 수집 항목·이용 목적·보관 기간을 자세히 적었어요(동의·처리·접속 기록, 탈퇴 뒤 누구 것인지 지운 채 남는 기록).",
  "소득·수급 정보에 본인 연 소득을 적었어요.",
  "만 14세 이상인지 확인하는 항목을 더했어요.",
];

const nothingChecked: Record<ConsentKey, boolean> = { age: false, terms: false, privacy: false, income: false };

export default function ConsentStep({ saving, onAgree, renewal }: ConsentStepProps) {
  const [checked, setCheckedState] = useState<Record<ConsentKey, boolean>>(nothingChecked);
  const [open, setOpen] = useState<ConsentKey | null>(null);
  // 다시 물을 때 켜 둔 소득 동의를 빼면 서버가 소득 값을 지운다. 한 번 더 누르게 한다(설정의 철회 확인과 같은 뜻).
  // 버튼은 그대로 두고 글만 바꿔 초점이 버튼에 남는다
  const [confirmDrop, setConfirmDrop] = useState(false);
  const confirmShownAt = useRef(0); // 두 번 빠르게 누른 것(더블 클릭)은 확인으로 치지 않는다
  const setChecked: typeof setCheckedState = (next) => {
    setConfirmDrop(false);
    setCheckedState(next);
  };
  const requiredDone = items.every((item) => !item.required || checked[item.key]);
  const all = items.every((item) => checked[item.key]);
  const dropsIncome = Boolean(renewal?.incomeOn) && !checked.income;

  return (
    <div>
      <h2 className="text-[22px] font-bold">{renewal ? "약관이 바뀌었어요" : "시작하기 전에 동의가 필요해요"}</h2>
      <p className="mt-1 text-[14px] text-[#667085]">
        {renewal
          ? "바뀐 내용을 보고 다시 동의해 주세요. 필수 항목에 동의하면 그대로 이어서 쓸 수 있어요."
          : "필수 항목에 동의하면 공고 판정을 시작할 수 있어요."}
      </p>
      {renewal && (
        <div className="mt-5 rounded-[14px] border border-[#dfe5ff] bg-[#f5f7ff] p-4">
          <p className="text-[13px] font-semibold text-[#344054]">바뀐 점</p>
          <ul className="mt-2 list-disc pl-5 text-[12px] leading-5 text-[#475467]">
            {CONSENT_CHANGES.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      <label className="mt-6 flex cursor-pointer items-center gap-3 rounded-[14px] border border-[#e5e7eb] p-4 text-[15px] font-bold">
        <input
          type="checkbox"
          checked={all}
          onChange={(event) => {
            const value = event.target.checked;
            setChecked({ age: value, terms: value, privacy: value, income: value });
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
            {/* 다시 물을 때 소득 동의를 빼면 서버가 소득 값을 지운다(API POST /me/consents). 체크하기 전에 알린다 */}
            {item.key === "income" && renewal?.incomeOn && !checked.income && (
              <p className="mt-2 pl-7 text-[12px] leading-5 text-[#b7791f]">
                지금 켜져 있어요. 다시 체크하지 않으면 입력한 소득·수급 정보가 지워져요.
              </p>
            )}
            {open === item.key && (
              <>
                <ul className="mt-3 list-disc pl-9 text-[12px] leading-5 text-[#667085]">
                  {item.summary.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                {item.fullText && (
                  <p className="mt-2 pl-9 text-[12px]">
                    <a
                      href={item.fullText}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-semibold text-[#4f6ef7] underline-offset-2 hover:underline"
                    >
                      개인정보 처리방침 전문 보기(새 탭)
                    </a>
                  </p>
                )}
              </>
            )}
          </div>
        ))}
      </div>
      {renewal && (
        // 설정은 다시 동의하기 전에도 열린다(AppFrame) — 동의하지 않고 탈퇴하거나 소득 동의를 철회할 수 있게
        <p className="mt-6 text-[12px] leading-5 text-[#667085]">
          동의하지 않으면 UNIPIVOT을 계속 쓸 수 없어요. 탈퇴는{" "}
          <Link href="/settings" className="font-semibold text-[#4f6ef7] underline-offset-2 hover:underline">
            설정
          </Link>
          에서 할 수 있어요.
        </p>
      )}
      {confirmDrop && dropsIncome && (
        <p role="alert" className="mt-6 rounded-[10px] bg-[#fff8e1] p-3 text-[13px] leading-6 text-[#7a4f00]">
          소득·수급 동의를 체크하지 않아서 입력한 소득·수급 정보가 지워져요. 그대로 계속하려면 한 번 더 눌러 주세요.
        </p>
      )}
      <div className="mt-8 flex justify-end">
        <Button
          onClick={() => {
            if (dropsIncome && !confirmDrop) {
              confirmShownAt.current = Date.now();
              setConfirmDrop(true);
            } else if (dropsIncome && Date.now() - confirmShownAt.current < 700) {
              return;
            } else onAgree({ incomeInfo: checked.income });
          }}
          disabled={!saving && !requiredDone}
          busy={saving}
        >
          {saving ? "저장 중" : confirmDrop && dropsIncome ? "지우고 계속" : "동의하고 계속"}
        </Button>
      </div>
    </div>
  );
}
