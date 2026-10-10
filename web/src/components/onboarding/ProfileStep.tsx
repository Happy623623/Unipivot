import Button from "@/components/Button";
import ProfileFieldInput from "@/components/profile/ProfileFieldInput";
import type { ProfileErrors, ProfileFormValues, ProfileKey, ProfileStepConfig } from "@/lib/profileFields";

interface ProfileStepProps {
  step: ProfileStepConfig;
  index: number;
  total: number;
  values: ProfileFormValues;
  errors: ProfileErrors;
  saving: boolean;
  onChange: (key: ProfileKey, value: string) => void;
  onBack?: () => void;
  onSkip: () => void;
  onNext: () => void;
}

export default function ProfileStep({
  step,
  index,
  total,
  values,
  errors,
  saving,
  onChange,
  onBack,
  onSkip,
  onNext,
}: ProfileStepProps) {
  const last = index === total - 1;

  return (
    <div>
      <div className="flex items-center justify-between text-[12px] font-semibold text-[#667085]">
        <span>프로필 {index + 1}/{total}</span>
        <button type="button" onClick={onSkip} className="hover:text-[#4f6ef7]">
          건너뛰기
        </button>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#e5e7eb]" aria-hidden="true">
        <div className="h-full rounded-full bg-[#4f6ef7]" style={{ width: `${((index + 1) / total) * 100}%` }} />
      </div>
      <h2 className="mt-6 text-[22px] font-bold">{step.title}</h2>
      <p className="mt-1 text-[14px] text-[#667085]">{step.description}</p>
      {step.sensitive && (
        <p className="mt-4 rounded-[10px] bg-[#fff8e1] p-3 text-[12px] font-semibold text-[#b7791f]">
          자격 판정에만 쓰고, 동의를 철회하거나 탈퇴하면 바로 지워요
        </p>
      )}
      <div className="mt-5 grid grid-cols-2 gap-4 max-[600px]:grid-cols-1">
        {step.fields.map((field) => (
          <ProfileFieldInput
            key={field.key}
            field={field}
            value={values[field.key]}
            error={errors[field.key]}
            onChange={(value) => onChange(field.key, value)}
          />
        ))}
      </div>
      <div className="mt-8 flex justify-between gap-2">
        {onBack ? <Button secondary onClick={onBack}>이전</Button> : <span />}
        <Button onClick={onNext} disabled={saving}>
          {saving ? "저장 중" : last ? "저장하고 계속" : "다음"}
        </Button>
      </div>
    </div>
  );
}
