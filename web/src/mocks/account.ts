import type { Department, Me, Profile, Settings } from "@/types/api";

export const mockToday = "2026-10-05";
export const mockNow = "2026-10-05T10:00:00+09:00";

export const me: Me = {
  user_id: "user-jinseo",
  display_name: "진서",
  hyin_verified: true,
  calendar_connected: true,
  lms: {
    status: "active",
    last_synced_at: "2026-10-05T09:30:00+09:00",
  },
  profile_completion: { filled: 9, total: 15 },
  consented: true,
  income_info_consented: true, // 목 프로필에 소득 값이 있다(동의 없이 소득 값을 둘 수 없다)
  unread_notifications: 3,
};

export const profile: Profile = {
  department: "컴퓨터학부",
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
  region_sigungu: "안산시",
  income_bracket: 4,
  median_income_pct: null,
  welfare_status: "none",
  is_international: false,
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
