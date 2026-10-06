-- ERD v0.8 마이그레이션 (ERD_v0.8_변경분.md 7장과 같은 내용). 레포에 이미 이 마이그레이션이 있으면 이 파일은 쓰지 않는다

-- =========================================================
-- ERD v0.7 → v0.8 마이그레이션 (디자인 초안 대조 반영, 2026-10-05)
-- v0.7 DDL을 실행한 DB에 이어서 실행한다
-- =========================================================

-- 1. 알림: 프로필 정보 필요 종류 + 앱 내 알림함 읽음 상태 (F-33, F-35)
alter type notification_type add value if not exists 'profile_needed';

alter table notifications add column read_at timestamptz;          -- null이면 안 읽음
create index notifications_user_recent_idx on notifications (user_id, scheduled_at desc);
create index notifications_user_unread_idx on notifications (user_id) where read_at is null;

-- 2. 사용자 설정 (F-06)
create table user_settings (
  user_id                   uuid primary key references profiles(id) on delete cascade,
  push_enabled              boolean not null default true,
  muted_notification_types  notification_type[] not null default '{}',  -- 끈 종류는 알림을 만들지 않음
  calendar_auto_lms         boolean not null default true,              -- LMS 과제 마감 자동 캘린더 등록
  updated_at                timestamptz not null default now()
);

-- 3. 약관·개인정보 동의 기록 (F-02)
alter table profiles
  add column terms_agreed_at    timestamptz,
  add column privacy_agreed_at  timestamptz,
  add column consent_version    text;                                  -- 동의한 약관 버전

-- 4. 공고 조회 기록: 새 공고 판정, 조회→준비 전환율 (F-40)
create table opportunity_views (
  user_id          uuid references profiles(id) on delete cascade,
  opportunity_id   uuid references opportunities(id) on delete cascade,
  first_viewed_at  timestamptz not null default now(),
  last_viewed_at   timestamptz not null default now(),
  primary key (user_id, opportunity_id)
);

-- 5. 필요 서류: 작성 예상 시간, 첨부 양식 링크 (F-30, F-41)
alter table opportunity_documents
  add column effort_minutes  smallint check (effort_minutes >= 0),    -- 표시용, 역산에는 쓰지 않음
  add column form_url        text;                                    -- 원문에 첨부된 신청 양식 링크
comment on column opportunity_documents.lead_days is '발급까지 걸리는 일수. 0이면 즉시 발급 (역산용)';

-- 6. 플래너: 서류 1개 = 준비 할 일 1개 (상세의 서류 체크와 같은 값, F-31, F-41)
create unique index planner_tasks_plan_document_uq
  on planner_tasks (prep_plan_id, document_id)
  where document_id is not null;

-- 7. LMS: 과목별 마지막 열람(새 자료 기준), 공지 한 줄 요약 (F-52, F-53)
alter table lms_courses add column last_viewed_at timestamptz default now();  -- 과목 행이 생긴 첫 동기화 시각부터 셈
alter table lms_announcements add column summary text;                         -- classify_announcement가 함께 생성

-- 8. 파일 원래 이름 (과목 상세 자료 탭, 문서함)
alter table files add column original_name text;

-- 9. RLS: 새 테이블은 본인 행만 읽기 (쓰기는 백엔드). Supabase REST 노출을 막기 위해 반드시 켠다
alter table user_settings     enable row level security;
alter table opportunity_views enable row level security;
create policy user_settings_select_own     on user_settings     for select using (auth.uid() = user_id);
create policy opportunity_views_select_own on opportunity_views for select using (auth.uid() = user_id);
