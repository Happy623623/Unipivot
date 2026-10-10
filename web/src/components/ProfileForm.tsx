import { useEffect, useMemo, useState } from "react";
import Button from "@/components/Button";
import ProfileFieldInput from "@/components/profile/ProfileFieldInput";
import {
  buildProfileSteps,
  fromFormValues,
  toFormValues,
  validateProfile,
  withoutIncome,
  type ProfileErrors,
  type ProfileFormValues,
} from "@/lib/profileFields";
import type { Department, Profile } from "@/types/api";

interface ProfileFormProps {
  profile: Profile;
  departments: Department[]; // GET /meta/departments
  incomeConsented: boolean; // GET /me의 income_info_consented
  saving?: boolean;
  submitLabel?: string;
  onCancel?: () => void;
  onSave: (profile: Profile) => void;
}

// 설정 화면용: 온보딩 4단계와 같은 항목 정의를 한 화면에 모두 보여준다
export default function ProfileForm({
  profile,
  departments,
  incomeConsented,
  saving = false,
  submitLabel = "저장",
  onCancel,
  onSave,
}: ProfileFormProps) {
  const [values, setValues] = useState<ProfileFormValues>(() => toFormValues(profile));
  const [errors, setErrors] = useState<ProfileErrors>({});
  const steps = useMemo(() => buildProfileSteps(departments), [departments]);
  // 소득 항목은 선택 동의를 했을 때만 입력받는다 (동의 전에는 저장하면 403)
  const editableFields = steps.flatMap((step) => (step.id === "income" && !incomeConsented ? [] : step.fields));

  useEffect(() => setValues(toFormValues(profile)), [profile]);

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const nextErrors = validateProfile(values, editableFields);
        setErrors(nextErrors);
        if (Object.keys(nextErrors).length > 0) return;
        const next = fromFormValues(values, profile);
        // 동의를 철회한 직후 화면에 남은 소득 값이 있어도 보내지 않는다
        onSave(incomeConsented ? next : withoutIncome(next));
      }}
    >
      <div className="flex flex-col gap-5">
        {steps.map((step) => (
          <section key={step.id} className={step.sensitive ? "rounded-[14px] bg-[#fff8e1] p-4" : ""}>
            <h3 className="text-[15px] font-bold">{step.title}</h3>
            {step.sensitive && (
              <p className="mt-1 text-[12px] font-semibold text-[#b7791f]">
                {incomeConsented
                  ? "자격 판정에만 쓰고, 동의를 철회하거나 탈퇴하면 바로 지워요"
                  : "소득·수급 정보는 선택 동의를 하면 입력할 수 있어요"}
              </p>
            )}
            {(step.id !== "income" || incomeConsented) && (
              <div className="mt-3 grid grid-cols-2 gap-4 max-[600px]:grid-cols-1">
                {step.fields.map((field) => (
                  <ProfileFieldInput
                    key={field.key}
                    field={field}
                    value={values[field.key]}
                    error={errors[field.key]}
                    onChange={(value) => setValues((current) => ({ ...current, [field.key]: value }))}
                  />
                ))}
              </div>
            )}
          </section>
        ))}
      </div>
      <div className="mt-6 flex justify-end gap-2">
        {onCancel && <Button secondary onClick={onCancel}>취소</Button>}
        <Button type="submit" disabled={saving}>
          {saving ? "저장 중" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
