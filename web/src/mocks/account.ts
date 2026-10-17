import type { Department, Me, Profile, Settings } from "@/types/api";

export const mockToday = "2026-10-05";
export const mockNow = "2026-10-05T10:00:00+09:00";

export const profile: Profile = {
  department: "컴퓨터학부",
  degree_program: "bachelor",
  grade: 3,
  enrollment_status: "enrolled",
  semesters_completed: 5,
  credits_total: 82,
  credits_last_semester: 18,
  gpa_total: 3.62,
  gpa_last_semester: 3.8,
  gpa_scale: 4.5,
  birth_date: "2003-04-18",
  military_service_months: null,
  region_sido: "경기도",
  region_sigungu: null, // 시·군·구 단위 지역 조건은 "정보 필요"가 된다(목 공고 youth-capability)
  income_bracket: null, // 목 공고 data-certificate의 "정보 필요"
  median_income_pct: null,
  annual_income: null,
  welfare_status: "none",
  job_status: "unemployed",
  is_international: false,
};

// GET /me의 profile_completion: 판정용 항목 중 채운 수. 평점 만점은 늘 값이 있어 세지 않는다(서버와 같다)
export function profileCompletion(value: Profile): Me["profile_completion"] {
  const entries = Object.entries(value).filter(([key]) => key !== "gpa_scale");
  return { filled: entries.filter(([, item]) => item !== null && item !== "").length, total: entries.length };
}

export const me: Me = {
  user_id: "user-jinseo",
  display_name: "진서",
  hyin_verified: true,
  calendar_connected: true,
  lms: {
    status: "active",
    last_synced_at: "2026-10-05T09:30:00+09:00",
  },
  profile_completion: profileCompletion(profile),
  consented: true,
  income_info_consented: true, // 목 프로필에 소득 값이 있다(동의 없이 소득 값을 둘 수 없다)
  unread_notifications: 3,
};

export const mockDepartments: Department[] = [
  { name: "컴퓨터학부", college: "소프트웨어융합대학", field_group: "공학" },
  { name: "인공지능학과", college: "소프트웨어융합대학", field_group: "공학" },
  { name: "경영학부", college: "경상대학", field_group: "사회" },
  { name: "디자인학부", college: "디자인대학", field_group: "예체능" },
];

export const settings: Settings = {
  push_enabled: true,
  muted_notification_types: [],
  calendar_auto_lms: true,
};
