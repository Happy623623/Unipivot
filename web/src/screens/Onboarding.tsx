import { useEffect, useMemo, useState } from "react";
import { getDepartments, getMe, getProfile, saveConsents, saveProfile, updateIncomeConsent } from "@/api/client";
import ConsentStep, { type ConsentChoice } from "@/components/onboarding/ConsentStep";
import IncomeConsentStep from "@/components/onboarding/IncomeConsentStep";
import LmsInviteStep from "@/components/onboarding/LmsInviteStep";
import ProfileStep from "@/components/onboarding/ProfileStep";
import Skeleton from "@/components/Skeleton";
import {
  buildProfileSteps,
  fromFormValues,
  toFormValues,
  validateProfile,
  type ProfileErrors,
  type ProfileFormValues,
} from "@/lib/profileFields";
import useAsyncData from "@/lib/useAsyncData";

// 동의 문구를 바꾸면 버전도 바꾼다 (profiles.consent_version에 남는다)
const CONSENT_VERSION = "2026-10-07";

type Stage =
  | { kind: "consent" }
  | { kind: "profile"; index: number }
  | { kind: "income_consent"; index: number }
  | { kind: "lms" };

interface OnboardingProps {
  onDone: () => void;
}

export default function Onboarding({ onDone }: OnboardingProps) {
  // 학과 목록을 못 불러와도 온보딩은 진행한다 (학과는 나중에 설정에서 고른다)
  const request = useAsyncData(
    () => Promise.all([getMe(), getProfile(), getDepartments().catch(() => [])]),
    [],
  );
  const [stage, setStage] = useState<Stage | null>(null);
  const [values, setValues] = useState<ProfileFormValues | null>(null);
  const [errors, setErrors] = useState<ProfileErrors>({});
  const [incomeConsented, setIncomeConsented] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const departments = request.data?.[2];
  const steps = useMemo(() => buildProfileSteps(departments ?? []), [departments]);

  useEffect(() => {
    if (!request.data) return;
    const [me, profile] = request.data;
    setValues(toFormValues(profile));
    setIncomeConsented(me.income_info_consented);
    setStage(me.consented ? { kind: "profile", index: 0 } : { kind: "consent" });
  }, [request.data]);

  if (request.error) {
    return <p className="mx-auto max-w-[640px] rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">{request.error}</p>;
  }
  if (!request.data || !stage || !values) {
    return <Skeleton className="mx-auto h-[420px] w-full max-w-[640px] rounded-[18px]" />;
  }

  const [me, profile] = request.data;
  const finish = () => (me.lms?.status === "active" ? onDone() : setStage({ kind: "lms" }));
  // 소득 단계는 선택 동의를 했을 때만 입력받고, 안 했으면 동의를 한 번 더 묻는다
  const openStep = (index: number) => {
    setErrors({});
    setError(null);
    if (index >= steps.length) finish();
    else if (steps[index].id === "income" && !incomeConsented) setStage({ kind: "income_consent", index });
    else setStage({ kind: "profile", index });
  };

  const agree = async (choice: ConsentChoice) => {
    setSaving(true);
    setError(null);
    try {
      const result = await saveConsents(CONSENT_VERSION, choice.incomeInfo);
      setIncomeConsented(result.income_info_agreed_at !== null);
      setStage({ kind: "profile", index: 0 });
    } catch {
      setError("동의를 저장하지 못했어요. 잠시 후 다시 눌러 주세요.");
    } finally {
      setSaving(false);
    }
  };

  const agreeIncome = async (index: number) => {
    setSaving(true);
    setError(null);
    try {
      await updateIncomeConsent(true);
      setIncomeConsented(true);
      setStage({ kind: "profile", index });
    } catch {
      setError("동의를 저장하지 못했어요. 잠시 후 다시 눌러 주세요.");
    } finally {
      setSaving(false);
    }
  };

  // 단계마다 저장해서, 중간에 나가도 입력한 값이 남는다
  const saveStep = async (index: number) => {
    const nextErrors = validateProfile(values, steps[index].fields);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    setSaving(true);
    setError(null);
    try {
      await saveProfile(fromFormValues(values, profile));
      openStep(index + 1);
    } catch {
      setError("프로필을 저장하지 못했어요. 입력한 값은 그대로 있으니 다시 눌러 주세요.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="mx-auto w-full max-w-[640px] rounded-[18px] border border-[#e5e7eb] bg-white p-8 max-[760px]:p-5">
      <p className="text-[13px] font-semibold text-[#4f6ef7]">UNIPIVOT 시작하기</p>
      <h1 className="mt-2 text-[24px] font-bold leading-[1.45]">{me.display_name}님에게 맞는 기회를 찾아드릴게요</h1>
      <div className="mt-6 border-t border-[#e5e7eb] pt-6">
        {stage.kind === "consent" && <ConsentStep saving={saving} onAgree={agree} />}
        {stage.kind === "profile" && (
          <ProfileStep
            step={steps[stage.index]}
            index={stage.index}
            total={steps.length}
            values={values}
            errors={errors}
            saving={saving}
            onChange={(key, value) => setValues((current) => (current ? { ...current, [key]: value } : current))}
            onBack={stage.index > 0 ? () => setStage({ kind: "profile", index: stage.index - 1 }) : undefined}
            onSkip={() => openStep(stage.index + 1)}
            onNext={() => saveStep(stage.index)}
          />
        )}
        {stage.kind === "income_consent" && (
          <IncomeConsentStep
            saving={saving}
            onAgree={() => agreeIncome(stage.index)}
            onSkip={() => openStep(stage.index + 1)}
            onBack={stage.index > 0 ? () => setStage({ kind: "profile", index: stage.index - 1 }) : undefined}
          />
        )}
        {stage.kind === "lms" && <LmsInviteStep onFinish={onDone} />}
        {error && <p role="alert" className="mt-4 text-[13px] text-[#c53030]">{error}</p>}
      </div>
    </section>
  );
}
