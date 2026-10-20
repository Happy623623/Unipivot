import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  consentRequired,
  errorMessage,
  fieldErrors,
  getDepartments,
  getMe,
  getProfile,
  recordEvent,
  saveProfile,
  updateIncomeConsent,
} from "@/api/client";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import ProfileFieldInput from "@/components/profile/ProfileFieldInput";
import {
  buildProfileSteps,
  changeValue,
  fromFormValues,
  resolveField,
  toFormValues,
  validateProfile,
  withoutError,
  withoutIncome,
  type ProfileErrors,
  type ProfileFieldConfig,
  type ProfileFormValues,
  type ProfileKey,
} from "@/lib/profileFields";
import type { Department, Profile } from "@/types/api";

interface ProfileInputModalProps {
  open: boolean;
  opportunityId: string;
  missingFields: string[]; // eligibility.missing_fields (요건 항목)
  onClose: () => void;
  onSaved: () => Promise<void>; // 공고를 다시 불러온다(서버가 그 자리에서 다시 판정한다)
}

interface Loaded {
  profile: Profile;
  departments: Department[];
  incomeConsented: boolean;
}

const INCOME_KEYS = new Set<ProfileKey>([
  "income_bracket",
  "median_income_pct",
  "annual_income",
  "welfare_status",
]);

// 나이 조건에서 생년월일이 이미 있으면 병역 복무 개월을 묻는다. 복무하지 않았으면 0을 넣어야 판정이 끝난다
const MILITARY_HINT = "복무 기간만큼 나이 상한을 늘려 주는 공고예요. 복무하지 않았으면 0을 입력해 주세요.";

function withContextHint(field: ProfileFieldConfig): ProfileFieldConfig {
  return field.key === "military_service_months" ? { ...field, hint: MILITARY_HINT } : field;
}

// 요건 항목 → 입력받을 프로필 항목. 나이는 생년월일(이미 있으면 병역 복무 개월)을,
// 거주지역은 시·도와 시·군·구를 묻는다(서버 판정 엔진의 "입력 필요" 문구와 같다)
function inputKeys(field: string, profile: Profile): ProfileKey[] {
  if (field === "age") return [profile.birth_date ? "military_service_months" : "birth_date"];
  if (field === "region") return ["region_sido", "region_sigungu"];
  return field in profile ? [field as ProfileKey] : [];
}

// 정보 입력(F-03): 판정에 빠진 항목만 받아 PATCH /me/profile로 저장한다. 창을 띄우면 profile_prompt_shown을 남긴다
export default function ProfileInputModal({ open, opportunityId, missingFields, onClose, onSaved }: ProfileInputModalProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [values, setValues] = useState<ProfileFormValues | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [errors, setErrors] = useState<ProfileErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [agreeing, setAgreeing] = useState(false);
  const shown = useRef(false);
  const fieldsKey = missingFields.join(",");

  useEffect(() => {
    if (!open) {
      shown.current = false;
      return;
    }
    if (!shown.current) {
      shown.current = true;
      recordEvent("profile_prompt_shown", opportunityId);
    }
    let active = true;
    setLoaded(null);
    setLoadError(null);
    setErrors({});
    setError(null);
    const fields = fieldsKey.split(",");
    // 학과 목록을 못 불러와도 다른 항목은 입력받는다(학과 칸에 안내가 뜬다)
    const departments = fields.includes("department") ? getDepartments().catch(() => []) : Promise.resolve([]);
    Promise.all([getProfile(), getMe(), departments])
      .then(([profile, me, departments]) => {
        if (!active) return;
        setLoaded({ profile, departments, incomeConsented: me.income_info_consented });
        setValues(toFormValues(profile));
      })
      .catch((caught: unknown) => {
        if (active) setLoadError(errorMessage(caught, "내 정보를 불러오지 못했어요. 창을 닫고 다시 열어 주세요."));
      });
    return () => {
      active = false;
    };
  }, [open, opportunityId, fieldsKey]);

  const fields = useMemo(() => {
    if (!loaded) return [];
    const configs = buildProfileSteps(loaded.departments).flatMap((step) => step.fields);
    const keys = [...new Set(fieldsKey.split(",").flatMap((field) => inputKeys(field, loaded.profile)))];
    return keys.flatMap((key) => configs.filter((config) => config.key === key).map(withContextHint));
  }, [loaded, fieldsKey]);
  const needsIncome = fields.some((field) => INCOME_KEYS.has(field.key));
  const editable = loaded?.incomeConsented ? fields : fields.filter((field) => !INCOME_KEYS.has(field.key));

  const agreeIncome = async () => {
    setAgreeing(true);
    setError(null);
    try {
      await updateIncomeConsent(true);
      setLoaded((current) => current && { ...current, incomeConsented: true });
    } catch (caught) {
      setError(errorMessage(caught, "동의하지 못했어요. 잠시 후 다시 눌러 주세요."));
    } finally {
      setAgreeing(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    // 저장 버튼은 busy라 누름은 막지만 입력란의 Enter(암묵적 제출)는 여기로 온다
    if (saving || !loaded || !values) return;
    const nextErrors = validateProfile(values, editable);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    const before = toFormValues(loaded.profile);
    if (editable.every((field) => values[field.key].trim() === before[field.key].trim())) {
      setError("새로 입력한 값이 없어요. 빈칸을 채운 뒤 저장해 주세요.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const next = fromFormValues(values, loaded.profile);
      await saveProfile(loaded.incomeConsented ? next : withoutIncome(next));
    } catch (caught) {
      setSaving(false);
      if (consentRequired(caught) === "income_info") {
        setLoaded({ ...loaded, incomeConsented: false });
        setError("소득·수급 정보는 선택 동의를 해야 저장할 수 있어요.");
        return;
      }
      setErrors(fieldErrors(caught));
      setError(errorMessage(caught, "저장하지 못했어요. 잠시 후 다시 눌러 주세요."));
      return;
    }
    await onSaved();
    setSaving(false);
  };

  return (
    <Modal open={open} title="정보 입력" onClose={onClose}>
      {loadError ? (
        <p role="alert" className="text-[13px] text-[#c53030]">{loadError}</p>
      ) : !loaded || !values ? (
        <p className="text-[13px] text-[#667085]">내 정보를 불러오고 있어요.</p>
      ) : (
        <form noValidate onSubmit={submit}>
          <p className="mb-4 text-[13px] text-[#667085]">이 공고를 판정하는 데 필요한 정보예요. 저장하면 바로 다시 판정해요.</p>
          {needsIncome && (
            <div className="mb-4 rounded-[10px] bg-[#fff8e1] p-3 text-[12px] text-[#b7791f]">
              {loaded.incomeConsented ? (
                <p>자격 판정에만 쓰고, 탈퇴하면 바로 지워요</p>
              ) : (
                <>
                  <p>소득·수급 정보는 선택 동의를 하면 입력할 수 있어요. 자격 판정에만 쓰고, 탈퇴하면 바로 지워요.</p>
                  <div className="mt-2">
                    <Button secondary onClick={agreeIncome} busy={agreeing}>
                      {agreeing ? "동의하는 중" : "동의하고 입력하기"}
                    </Button>
                  </div>
                </>
              )}
            </div>
          )}
          <div className="flex flex-col gap-4">
            {editable.map((field) => (
              <ProfileFieldInput
                key={field.key}
                field={resolveField(field, values)}
                value={values[field.key]}
                error={errors[field.key]}
                onChange={(value) => {
                  setValues((current) => current && changeValue(current, field.key, value));
                  setErrors((current) => withoutError(current, field.key));
                }}
              />
            ))}
          </div>
          {fields.length === 0 && (
            <p className="text-[13px] text-[#667085]">여기서 입력할 수 있는 항목이 없어요. 원문을 확인해 주세요.</p>
          )}
          {error && <p role="alert" className="mt-4 text-[13px] text-[#c53030]">{error}</p>}
          <div className="mt-6 flex justify-end gap-2">
            <Button secondary onClick={onClose}>취소</Button>
            <Button type="submit" disabled={!saving && editable.length === 0} busy={saving}>
              {saving ? "다시 판정 중" : "저장하고 다시 판정"}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
