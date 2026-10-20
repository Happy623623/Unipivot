import { useEffect, useMemo, useState } from "react";
import {
  consentRequired,
  errorMessage,
  fieldErrors,
  getDepartments,
  getMe,
  getProfile,
  saveConsents,
  saveProfile,
  updateIncomeConsent,
} from "@/api/client";
import ConsentStep, { type ConsentChoice } from "@/components/onboarding/ConsentStep";
import IncomeConsentStep from "@/components/onboarding/IncomeConsentStep";
import LmsInviteStep from "@/components/onboarding/LmsInviteStep";
import ProfileStep from "@/components/onboarding/ProfileStep";
import Skeleton from "@/components/Skeleton";
import {
  buildProfileSteps,
  changeValue,
  fromFormValues,
  toFormValues,
  validateProfile,
  withoutError,
  withoutIncome,
  type ProfileErrors,
  type ProfileFormValues,
} from "@/lib/profileFields";
import useAsyncData from "@/lib/useAsyncData";
import useSessionWatch from "@/lib/useSessionWatch";

// 동의 문구를 바꾸면 버전도 바꾼다 (profiles.consent_version에 남는다)
const CONSENT_VERSION = "2026-10-07";
const CONSENT_FAILED = "동의를 저장하지 못했어요. 잠시 후 다시 눌러 주세요.";
const PROFILE_FAILED = "프로필을 저장하지 못했어요. 입력한 값은 그대로 있으니 다시 눌러 주세요.";

type Stage =
  | { kind: "consent" }
  | { kind: "profile"; index: number }
  | { kind: "income_consent"; index: number }
  | { kind: "lms" };

interface OnboardingProps {
  onDone: () => void;
}

export default function Onboarding({ onDone }: OnboardingProps) {
  useSessionWatch(); // 다른 탭에서 로그아웃·탈퇴하면 입력 중인 프로필을 내리고 로그인 화면으로
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
  // 이미 LearningX를 연결한 사람은 마지막 LMS 단계를 건너뛴다
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
    } catch (caught) {
      setError(errorMessage(caught, CONSENT_FAILED));
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
    } catch (caught) {
      if (consentRequired(caught) === "terms_privacy") setStage({ kind: "consent" });
      setError(errorMessage(caught, CONSENT_FAILED));
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
      const next = fromFormValues(values, profile);
      // 소득 3항목은 선택 동의를 했을 때만 보낸다 (설정의 ProfileForm과 같다)
      await saveProfile(incomeConsented ? next : withoutIncome(next));
      openStep(index + 1);
    } catch (caught) {
      // 동의가 빠졌으면 그 동의를 다시 묻는다(API 13장). 항목 오류는 입력란 아래에 보여 준다
      const consent = consentRequired(caught);
      const onIncomeStep = steps[index].id === "income";
      setErrors(fieldErrors(caught) as ProfileErrors);
      setError(errorMessage(caught, PROFILE_FAILED));
      if (consent === "terms_privacy") setStage({ kind: "consent" });
      if (consent === "income_info") {
        // 다른 곳에서 소득 동의를 철회했다. 소득 단계면 동의부터 다시 묻고, 아니면 소득 값은 빼고 다시 저장하게 한다
        setIncomeConsented(false);
        if (onIncomeStep) setStage({ kind: "income_consent", index });
        else setError("소득·수급 정보 동의가 꺼져 있어요. 소득 정보는 빼고 저장하니 다시 눌러 주세요.");
      }
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
            onChange={(key, value) => {
              setValues((current) => (current ? changeValue(current, key, value) : current));
              setErrors((current) => withoutError(current, key));
            }}
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
