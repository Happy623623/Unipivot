import type { Department, Profile } from "@/types/api";

// 판정용 프로필 17개 항목을 온보딩 4단계와 설정 화면이 함께 쓴다 (ERD profiles 컬럼과 1:1)
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
  step?: number;
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

const SIDO = [
  "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시",
  "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도",
  "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도",
];

// 소득·수급 3항목은 선택 동의(소득·수급 정보)를 해야 저장된다 (동의 없이 값을 보내면 403)
export function withoutIncome(profile: Profile): Profile {
  return { ...profile, income_bracket: null, median_income_pct: null, welfare_status: null };
}

// 학과 선택지는 GET /meta/departments 목록으로 만든다
export function buildProfileSteps(departments: Department[]): ProfileStepConfig[] {
  return [
    {
      id: "academic",
      title: "학적",
      description: "학과·학년·학적 상태 조건을 판정해요.",
      fields: [
        {
          key: "department",
          label: "학과",
          kind: "select",
          options: departments.map((department) => ({ value: department.name, label: department.name })),
          hint: departments.length === 0 ? "학과 목록을 불러오지 못했어요. 나중에 설정에서 고를 수 있어요." : undefined,
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
        { key: "region_sigungu", label: "거주 시·군·구", kind: "text", placeholder: "예: 안산시 단원구" },
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
]);
const booleanKeys = new Set<ProfileKey>(["is_international"]);

export function toFormValues(profile: Profile): ProfileFormValues {
  const values = {} as ProfileFormValues;
  for (const key of Object.keys(profile) as ProfileKey[]) {
    const value = profile[key];
    values[key] = value === null || value === undefined ? "" : String(value);
  }
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
    if (raw === "" || field.kind !== "number") continue;
    const value = Number(raw);
    if (Number.isNaN(value)) errors[field.key] = "숫자로 입력해 주세요.";
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
