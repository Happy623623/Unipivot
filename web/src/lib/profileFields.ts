import { SIDO, SIGUNGU_HINT, sigunguOf, squashSpaces } from "@/lib/regions";
import type { DegreeProgram, Department, Profile } from "@/types/api";

// 판정용 프로필 18개 항목을 온보딩 4단계와 설정 화면이 함께 쓴다 (ERD profiles 컬럼과 1:1)
export type ProfileKey = keyof Profile;
export type ProfileFormValues = Record<ProfileKey, string>;
export type ProfileErrors = Partial<Record<ProfileKey, string>>;

export interface ProfileFieldConfig {
  key: ProfileKey;
  label: string;
  kind: "text" | "number" | "date" | "select";
  options?: { value: string; label: string }[];
  allowEmpty?: boolean; // select에 "선택 안 함"을 둘지 (기본 true)
  min?: number;
  max?: number;
  step?: number; // 1이면 정수만 받는다 (서버 int 항목)
  maxLength?: number; // 글자 수 상한 (서버 max_length와 같게)
  unit?: string;
  placeholder?: string;
  hint?: string;
}

export interface ProfileStepConfig {
  id: "academic" | "grades" | "age_region" | "income";
  title: string;
  description: string;
  sensitive?: boolean;
  fields: ProfileFieldConfig[];
}

// 학위과정 이름 (서버 판정표의 학위과정 문구와 같다)
export const DEGREE_LABELS: Record<DegreeProgram, string> = {
  bachelor: "학부",
  master: "석사",
  doctoral: "박사",
  integrated: "석박사통합",
};

// 소득·수급 3항목은 선택 동의(소득·수급 정보)를 해야 저장된다 (동의 없이 값을 보내면 403)
export function withoutIncome(profile: Profile): Profile {
  return { ...profile, income_bracket: null, median_income_pct: null, annual_income: null, welfare_status: null };
}

// 거주 시·군·구 선택지는 고른 시·도에 따라 바뀐다. 목록에 없는 값(직접 입력하던 때의 값)은 그대로 보여 주고 다시 고르게 한다
export function resolveField(field: ProfileFieldConfig, values: ProfileFormValues): ProfileFieldConfig {
  if (field.key !== "region_sigungu") return field;
  const sido = values.region_sido;
  const names = sigunguOf(sido);
  const current = values.region_sigungu;
  const options = names.map((name) => ({ value: name, label: name }));
  const unlisted = current !== "" && !names.includes(current);
  if (unlisted) options.unshift({ value: current, label: `${current} (목록에 없음)` });
  const hint =
    unlisted && names.length > 0
      ? "목록에 없는 값이에요. 목록에서 다시 골라 주세요."
      : unlisted || !sido
        ? unlistedMessage(sido)
        : names.length === 0
          ? "이 시·도는 시·군·구가 없어요."
          : SIGUNGU_HINT[sido] ?? field.hint;
  return { ...field, options, hint };
}

// 목록에 없는 시·군·구를 어떻게 고치는지
function unlistedMessage(sido: string): string {
  if (!sido) return "거주 시·도를 먼저 골라 주세요.";
  if (sigunguOf(sido).length === 0) return "이 시·도는 시·군·구가 없어요. '선택 안 함'으로 바꿔 주세요.";
  return "목록에서 다시 골라 주세요.";
}

// 설정 요약의 지역. 목록에 없는 시·군·구(직접 입력하던 때의 값)면 다시 고르라고 붙인다
export function regionText(profile: Profile): string {
  const text = [profile.region_sido, profile.region_sigungu].filter(Boolean).join(" ");
  const sigungu = squashSpaces(profile.region_sigungu ?? "");
  const listed = sigungu === "" || sigunguOf(profile.region_sido ?? "").includes(sigungu);
  return !text ? "미입력" : listed ? text : `${text} (다시 골라 주세요)`;
}

// 값 하나를 바꾼다. 시·도를 바꾸면 시·군·구를 비운다(같은 이름의 구가 다른 시·도에도 있다)
export function changeValue(values: ProfileFormValues, key: ProfileKey, value: string): ProfileFormValues {
  const next = { ...values, [key]: value };
  if (key === "region_sido" && value !== values.region_sido) next.region_sigungu = "";
  return next;
}

// 값을 바꾼 항목의 오류를 지운다. 시·도를 바꾸면 시·군·구 오류도 지운다
export function withoutError(errors: ProfileErrors, key: ProfileKey): ProfileErrors {
  const next = { ...errors };
  delete next[key];
  if (key === "region_sido") delete next.region_sigungu;
  return next;
}

// 학과 선택지는 GET /meta/departments 목록으로 만든다
export function buildProfileSteps(departments: Department[]): ProfileStepConfig[] {
  return [
    {
      id: "academic",
      title: "학적",
      description: "학과·학위과정·학년·학적 상태 조건을 판정해요.",
      fields: [
        {
          key: "department",
          label: "학과",
          kind: "select",
          options: departments.map((department) => ({ value: department.name, label: department.name })),
          hint: departments.length === 0 ? "학과 목록을 불러오지 못했어요. 나중에 설정에서 고를 수 있어요." : undefined,
        },
        {
          key: "degree_program",
          label: "학위과정",
          kind: "select",
          options: Object.entries(DEGREE_LABELS).map(([value, label]) => ({ value, label })),
          hint: "지금 다니는 과정이에요. 졸업했으면 마지막으로 다닌 과정을 골라요.",
        },
        {
          key: "grade",
          label: "학년",
          kind: "select",
          options: [1, 2, 3, 4, 5, 6].map((grade) => ({ value: String(grade), label: `${grade}학년` })),
        },
        {
          key: "enrollment_status",
          label: "학적 상태",
          kind: "select",
          options: [
            { value: "enrolled", label: "재학" },
            { value: "on_leave", label: "휴학" },
            { value: "deferred_graduation", label: "졸업 유예" },
            { value: "graduated", label: "졸업" },
          ],
        },
        {
          key: "semesters_completed",
          label: "마친 학기 수",
          kind: "number",
          min: 0,
          max: 16,
          step: 1,
          unit: "학기",
          hint: "지금 다니는 학기는 빼고 세요. \"8학기 이내\" 같은 조건을 판정할 때 써요.",
        },
        {
          key: "job_status",
          label: "취업 상태",
          kind: "select",
          options: [
            { value: "unemployed", label: "미취업" },
            { value: "employed", label: "재직" },
            { value: "self_employed", label: "자영업" },
            { value: "freelancer", label: "프리랜서" },
            { value: "short_term", label: "단기근로" },
            { value: "daily_worker", label: "일용근로" },
            { value: "founder", label: "(예비)창업자" },
            { value: "farmer", label: "영농종사" },
          ],
          hint: "청년 정책은 미취업·재직 조건을 자주 걸어요. 재학 중이고 일하지 않으면 미취업이에요.",
        },
        {
          key: "is_international",
          label: "외국인 유학생",
          kind: "select",
          options: [
            { value: "false", label: "아니요" },
            { value: "true", label: "예" },
          ],
          hint: "유학생 전용 공고를 판정할 때 써요.",
        },
      ],
    },
    {
      id: "grades",
      title: "성적",
      description: "교내 장학금은 대부분 직전학기 성적을 봐요.",
      fields: [
        { key: "credits_total", label: "누적 이수학점", kind: "number", min: 0, max: 200, step: 0.5, unit: "학점" },
        { key: "credits_last_semester", label: "직전학기 이수학점", kind: "number", min: 0, max: 30, step: 0.5, unit: "학점" },
        { key: "gpa_total", label: "누적 평점", kind: "number", min: 0, max: 4.5, step: 0.01 },
        { key: "gpa_last_semester", label: "직전학기 장학용 평점(F 포함)", kind: "number", min: 0, max: 4.5, step: 0.01 },
        {
          key: "gpa_scale",
          label: "평점 만점",
          kind: "select",
          allowEmpty: false,
          options: [
            { value: "4.5", label: "4.5" },
            { value: "4.3", label: "4.3" },
          ],
        },
      ],
    },
    {
      id: "age_region",
      title: "나이·지역",
      description: "청년 정책은 만 나이와 주민등록 주소를 봐요.",
      fields: [
        { key: "birth_date", label: "생년월일", kind: "date" },
        {
          key: "military_service_months",
          label: "병역 복무 개월 수",
          kind: "number",
          min: 0,
          max: 60,
          step: 1,
          unit: "개월",
          hint: "해당자만 입력해요. 복무 기간만큼 청년 나이 상한이 늘어나는 정책이 있어요.",
        },
        {
          key: "region_sido",
          label: "거주 시·도",
          kind: "select",
          options: SIDO.map((sido) => ({ value: sido, label: sido })),
          hint: "주민등록 주소 기준이에요.",
        },
        // 선택지는 resolveField가 고른 시·도로 채운다(구가 있는 시는 구까지)
        { key: "region_sigungu", label: "거주 시·군·구", kind: "select", hint: "구가 있는 시는 구까지 골라요." },
      ],
    },
    {
      id: "income",
      title: "소득",
      description: "소득 기준이 있는 장학금·청년 정책을 판정해요. 모르면 비워 두세요.",
      sensitive: true,
      fields: [
        {
          key: "income_bracket",
          label: "학자금 지원구간",
          kind: "select",
          options: Array.from({ length: 11 }, (_, bracket) => ({
            value: String(bracket),
            label: bracket === 0 ? "기초·차상위" : `${bracket}구간`,
          })),
        },
        {
          key: "median_income_pct",
          label: "기준 중위소득",
          kind: "number",
          min: 0,
          max: 500,
          step: 1,
          unit: "%",
          hint: "가구 기준이에요. 학자금 지원구간과 서로 바꿔 계산하지 않아요.",
        },
        {
          key: "annual_income",
          label: "본인 연 소득",
          kind: "number",
          min: 0,
          max: 30000,
          step: 100,
          unit: "만 원",
          hint: "본인 소득만 적어요. 가구 합산이 아니라 내 연 소득이에요. 모르면 비워 두세요.",
        },
        {
          key: "welfare_status",
          label: "기초생활수급·차상위",
          kind: "select",
          options: [
            { value: "none", label: "해당 없음" },
            { value: "near_poverty", label: "차상위계층" },
            { value: "basic_livelihood", label: "기초생활수급" },
          ],
        },
      ],
    },
  ];
}

const numericKeys = new Set<ProfileKey>([
  "grade", "semesters_completed", "credits_total", "credits_last_semester", "gpa_total",
  "gpa_last_semester", "gpa_scale", "military_service_months", "income_bracket", "median_income_pct",
  "annual_income",
]);
const booleanKeys = new Set<ProfileKey>(["is_international"]);

export function toFormValues(profile: Profile): ProfileFormValues {
  const values = {} as ProfileFormValues;
  for (const key of Object.keys(profile) as ProfileKey[]) {
    const value = profile[key];
    values[key] = value === null || value === undefined ? "" : String(value);
  }
  // 직접 입력하던 때의 시·군·구는 띄어쓰기를 맞춰 목록 값과 비교한다
  values.region_sigungu = squashSpaces(values.region_sigungu ?? "");
  return values;
}

// 빈 칸은 null(판정 불가로 남김), 숫자 항목은 number, 예/아니요 항목은 boolean으로 바꾼다
export function fromFormValues(values: ProfileFormValues, base: Profile): Profile {
  const next: Record<string, unknown> = { ...base };
  for (const key of Object.keys(values) as ProfileKey[]) {
    const raw = values[key].trim();
    if (key === "gpa_scale") next[key] = raw === "" ? base.gpa_scale : Number(raw);
    else if (raw === "") next[key] = null;
    else if (booleanKeys.has(key)) next[key] = raw === "true";
    else next[key] = numericKeys.has(key) ? Number(raw) : raw;
  }
  return next as unknown as Profile;
}

export function validateProfile(values: ProfileFormValues, fields: ProfileFieldConfig[]): ProfileErrors {
  const errors: ProfileErrors = {};
  for (const field of fields) {
    const raw = values[field.key]?.trim() ?? "";
    if (field.key === "region_sigungu" && raw !== "" && !sigunguOf(values.region_sido).includes(raw)) {
      errors.region_sigungu = unlistedMessage(values.region_sido);
    }
    if (raw === "" || field.kind !== "number") continue;
    const value = Number(raw);
    if (Number.isNaN(value)) errors[field.key] = "숫자로 입력해 주세요.";
    else if (field.step === 1 && !Number.isInteger(value)) errors[field.key] = "소수점 없이 입력해 주세요.";
    else if (field.min !== undefined && value < field.min) errors[field.key] = `${field.min} 이상으로 입력해 주세요.`;
    else if (field.max !== undefined && value > field.max) errors[field.key] = `${field.max} 이하로 입력해 주세요.`;
  }
  const scale = Number(values.gpa_scale || "4.5");
  for (const key of ["gpa_total", "gpa_last_semester"] as const) {
    const onStep = fields.some((field) => field.key === key);
    if (onStep && values[key] !== "" && Number(values[key]) > scale) {
      errors[key] = `평점 만점(${scale})보다 클 수 없어요.`;
    }
  }
  return errors;
}
