import Button from "@/components/Button";

interface IncomeConsentStepProps {
  saving: boolean;
  onAgree: () => void;
  onSkip: () => void;
  onBack?: () => void;
}

// 동의 단계에서 선택 동의를 하지 않은 사람에게 소득 단계 앞에서 한 번 더 묻는다
export default function IncomeConsentStep({ saving, onAgree, onSkip, onBack }: IncomeConsentStepProps) {
  return (
    <div>
      <h2 className="text-[22px] font-bold">소득 정보도 입력할까요?</h2>
      <p className="mt-1 text-[14px] leading-6 text-[#667085]">
        소득 기준이 있는 장학금·청년 정책을 판정하려면 선택 동의가 필요해요. 동의하지 않아도 다른 공고는 그대로
        판정해요.
      </p>
      <ul className="mt-4 list-disc rounded-[10px] bg-[#fff8e1] py-3 pl-8 pr-3 text-[12px] leading-5 text-[#b7791f]">
        <li>수집 항목: 학자금 지원구간, 기준 중위소득 %, 기초생활수급·차상위 여부</li>
        <li>이용 목적: 소득 기준이 있는 공고의 지원 자격 판정</li>
        <li>보관: 설정에서 동의를 철회하거나 탈퇴하면 바로 지워요</li>
      </ul>
      <div className="mt-8 flex justify-between gap-2">
        {onBack ? <Button secondary onClick={onBack}>이전</Button> : <span />}
        <div className="flex gap-2">
          <Button secondary onClick={onSkip}>건너뛰기</Button>
          <Button onClick={onAgree} disabled={saving}>
            {saving ? "저장 중" : "동의하고 입력"}
          </Button>
        </div>
      </div>
    </div>
  );
}
