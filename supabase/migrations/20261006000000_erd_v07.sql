-- ERD v0.7 DDL (docs/ERD_v0.7.md 7장 DDL과 같은 내용). 레포에 이미 이 마이그레이션이 있으면 이 파일은 쓰지 않는다

-- =========================================================
-- ENUM
-- =========================================================
create type source_type           as enum ('school_notice','youth_policy','contest','poster','lms_announcement');
create type opportunity_category  as enum ('scholarship','school_program','youth_policy','contest','activity','research','exam','etc');
create type opportunity_status    as enum ('active','hidden','merged','expired');
create type req_field             as enum ('department','grade','enrollment_status','semesters_completed','credits_total','credits_last_semester',
                                           'gpa_total','gpa_last_semester','age','region','income_bracket','median_income_pct',
                                           'welfare_status','other');
create type welfare_status        as enum ('none','near_poverty','basic_livelihood');   -- 차상위, 기초생활수급
create type req_operator          as enum ('eq','neq','in','not_in','gte','lte','between');
create type eligibility_status    as enum ('eligible','ineligible','undetermined');
create type enrollment_status     as enum ('enrolled','on_leave','deferred_graduation','graduated');
create type file_kind             as enum ('poster','syllabus','lecture_material');
create type file_origin           as enum ('upload','lms_attachment');
create type task_source           as enum ('prep_plan','syllabus','lms_assignment','lms_announcement','manual');
create type calendar_provider     as enum ('google','ics','device');
create type syllabus_item_type    as enum ('midterm','final','presentation','assignment','etc');
create type job_status            as enum ('pending','running','succeeded','failed');
create type run_trigger           as enum ('batch_crawl','poster_upload','prepare','syllabus_upload','material_upload','material_translate','lms_sync','notify','eval');
create type notification_type     as enum ('new_eligible','new_assignment','new_material','schedule_change','task_due','deadline_soon');
create type report_reason         as enum ('wrong_info','duplicate','expired','inappropriate');
create type lms_connection_status as enum ('active','error','disconnected');
create type lms_submission_state  as enum ('unsubmitted','submitted','graded','pending_review');
create type announcement_category as enum ('schedule_change','material','opportunity','general');

-- =========================================================
-- 1. 사용자
-- =========================================================
create table profiles (
  id                     uuid primary key references auth.users(id) on delete cascade,
  display_name           text,                                   -- Google 이름, 표시할 때 마스킹
  school                 text default 'HYU_ERICA',
  department             text,
  grade                  smallint check (grade between 1 and 6),
  enrollment_status      enrollment_status,
  credits_total          numeric(5,1),
  credits_last_semester  numeric(4,1),
  gpa_total              numeric(3,2),
  gpa_last_semester      numeric(3,2),                           -- 직전학기 장학용 평점평균 (F 포함)
  semesters_completed    smallint,                               -- 이수 학기 수 ("정규 학기 이내" 판정)
  gpa_scale              numeric(2,1) default 4.5,
  birth_date             date,                                   -- 만 나이 계산용
  military_service_months smallint,                              -- 병역 복무 개월 (청년 연령 상한 연장)
  region_sido            text,
  region_sigungu         text,
  income_bracket         smallint check (income_bracket between 0 and 10),  -- 학자금 지원구간
  median_income_pct      smallint,                               -- 기준 중위소득 % (가구 기준)
  welfare_status         welfare_status,                         -- 기초생활수급 / 차상위 여부
  admission_year         smallint,                               -- HY-in 인증 시 자동 입력
  hyin_verified_at       timestamptz,                            -- HY-in 재학생 인증 시각 (학번·성명은 저장 안 함)
  profile_updated_at     timestamptz default now(),
  created_at             timestamptz default now()
);

create table oauth_tokens (
  user_id        uuid references profiles(id) on delete cascade,
  provider       text not null default 'google',
  access_token   text,                                           -- 암호화 저장 (Supabase Vault 등)
  refresh_token  text,                                           -- 암호화 저장
  scope          text,
  expires_at     timestamptz,
  primary key (user_id, provider)
);

create table push_subscriptions (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references profiles(id) on delete cascade,
  endpoint    text not null unique,
  p256dh      text not null,
  auth        text not null,
  user_agent  text,
  created_at  timestamptz default now()
);

-- =========================================================
-- 2. 로깅
-- =========================================================
create table agent_runs (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid references profiles(id) on delete set null,   -- 배치 실행은 null
  trigger_type   run_trigger not null,
  status         job_status not null default 'running',
  scenario_code  text,                                              -- 평가 실행 시 시나리오 번호
  started_at     timestamptz default now(),
  finished_at    timestamptz,
  latency_ms     int,
  input_tokens   int default 0,
  output_tokens  int default 0,
  cost_usd       numeric(10,6) default 0,
  error_message  text
);
create index on agent_runs (trigger_type, started_at);

create table tool_calls (
  id          uuid primary key default gen_random_uuid(),
  run_id      uuid not null references agent_runs(id) on delete cascade,
  seq         smallint not null,
  tool_name   text not null,
  input       jsonb,                                              -- 토큰·비밀값은 넣지 않음
  output      jsonb,
  status      job_status not null,
  latency_ms  int,
  created_at  timestamptz default now()
);
create index on tool_calls (run_id, seq);

create table llm_calls (
  id             uuid primary key default gen_random_uuid(),
  run_id         uuid not null references agent_runs(id) on delete cascade,
  tool_call_id   uuid references tool_calls(id) on delete set null,
  provider       text not null,                                   -- anthropic / google
  model          text not null,
  input_tokens   int not null,
  output_tokens  int not null,
  cost_usd       numeric(10,6),
  latency_ms     int,
  created_at     timestamptz default now()
);
create index on llm_calls (run_id);

-- =========================================================
-- 3. LMS 연결 · 수강 과목 (사용자별)
-- =========================================================
create table lms_connections (
  user_id         uuid primary key references profiles(id) on delete cascade,
  lms             text not null default 'hyu_learningx',
  access_token    text not null,                -- 개인 액세스 토큰, 암호화 저장
  token_last4     text,                         -- 화면 표시용
  canvas_user_id  bigint,
  status          lms_connection_status not null default 'active',
  last_synced_at  timestamptz,
  last_error      text,
  created_at      timestamptz default now()
);

create table lms_courses (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references profiles(id) on delete cascade,
  canvas_course_id  bigint not null,
  name              text not null,              -- 예: 202620HY23534_기계학습
  term              text,                       -- 예: 2026-2
  portal_year       smallint,                   -- 포털 계획서 링크용, 과목명에서 파싱 (예: 2026)
  portal_term       smallint,                   -- 예: 20
  portal_course_no  text,                       -- 예: 23525
  is_active         boolean default true,
  synced_at         timestamptz default now(),
  unique (user_id, canvas_course_id)
);
create index on lms_courses (canvas_course_id);

-- =========================================================
-- 4. 업로드 파일
-- =========================================================
create table files (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references profiles(id) on delete cascade,
  lms_course_id  uuid references lms_courses(id) on delete set null,   -- 과목 지정
  kind           file_kind not null,
  origin         file_origin not null default 'upload',
  external_ref   text,                          -- lms_attachment면 Canvas 첨부 ID
  storage_path   text not null,
  mime_type      text,
  size_bytes     bigint,
  page_count     int,
  sha256         text not null,
  created_at     timestamptz default now(),
  unique (user_id, external_ref)                -- 같은 첨부 중복 수집 방지
);
create index on files (user_id, sha256);

-- =========================================================
-- 5. 공고 · 요건
-- =========================================================
create table sources (
  id                 uuid primary key default gen_random_uuid(),
  type               source_type not null,
  name               text not null,             -- 예: ERICA 장학공지, 온통청년, LearningX 과목 공지
  base_url           text,
  is_active          boolean default true,
  last_collected_at  timestamptz
);

create table opportunities (
  id                        uuid primary key default gen_random_uuid(),
  source_id                 uuid references sources(id),
  source_type               source_type not null,
  external_id               text,               -- 게시글 번호, 정책 ID, Canvas 공지 ID
  category                  opportunity_category not null default 'etc',
  title                     text not null,
  organizer                 text,
  original_url              text,
  raw_text                  text,
  easy_summary              text,               -- 쉬운 설명
  apply_start_at            timestamptz,
  deadline_at               timestamptz,
  difficulty                smallint check (difficulty between 1 and 3),  -- 대체 추천용 (P1)
  extraction_confidence     numeric(3,2),
  needs_review              boolean default false,                        -- 원문 확인 필요 배지
  visible_canvas_course_id  bigint,             -- null이면 전체 공개, 값이 있으면 해당 과목 수강생만
  uploaded_by               uuid references profiles(id) on delete set null,
  poster_file_id            uuid references files(id) on delete set null,
  status                    opportunity_status not null default 'active',
  merged_into_id            uuid references opportunities(id),
  dedupe_key                text,               -- 정규화한 제목+주최+마감일
  extraction_run_id         uuid references agent_runs(id) on delete set null,
  created_at                timestamptz default now(),
  updated_at                timestamptz default now(),
  unique (source_id, external_id)
);
create index on opportunities (status, deadline_at);
create index on opportunities (dedupe_key);
create index on opportunities (visible_canvas_course_id) where visible_canvas_course_id is not null;

create table requirements (
  id              uuid primary key default gen_random_uuid(),
  opportunity_id  uuid not null references opportunities(id) on delete cascade,
  field           req_field not null,
  operator        req_operator not null,
  value           jsonb not null,               -- 3.0 / ["경기도 안산시"] / {"min":19,"max":34}
  evidence_text   text,                         -- 근거 원문 문장
  is_ambiguous    boolean default false,
  created_at      timestamptz default now()
);
create index on requirements (opportunity_id);

create table opportunity_documents (
  id              uuid primary key default gen_random_uuid(),
  opportunity_id  uuid not null references opportunities(id) on delete cascade,
  name            text not null,                -- 예: 재학증명서
  issuer          text,                         -- 발급처
  how_to          text,                         -- 발급 방법
  lead_days       smallint,                     -- 준비 소요 일수 (역산용)
  is_required     boolean default true
);

create table opportunity_reports (
  opportunity_id  uuid references opportunities(id) on delete cascade,
  reporter_id     uuid references profiles(id) on delete cascade,
  reason          report_reason not null,
  detail          text,
  created_at      timestamptz default now(),
  primary key (opportunity_id, reporter_id)
);

-- =========================================================
-- 6. 판정
-- =========================================================
create table eligibility_results (
  user_id            uuid references profiles(id) on delete cascade,
  opportunity_id     uuid references opportunities(id) on delete cascade,
  status             eligibility_status not null,
  condition_results  jsonb not null,            -- [{requirement_id, outcome: pass|fail|unknown, user_value}]
  missing_fields     req_field[],               -- 판정 불가 원인 항목
  reason_text        text,                      -- 탈락 사유 문장
  evaluated_at       timestamptz default now(),
  primary key (user_id, opportunity_id)
);
create index on eligibility_results (user_id, status);

-- =========================================================
-- 7. LMS 과제 (사용자별) · 모듈 항목 · 공지 (과목 공통)
-- =========================================================
create table lms_assignments (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null references profiles(id) on delete cascade,
  lms_course_id         uuid not null references lms_courses(id) on delete cascade,
  canvas_assignment_id  bigint not null,
  title                 text not null,
  due_at                timestamptz,
  html_url              text,
  submission_state      lms_submission_state not null default 'unsubmitted',
  submitted_at          timestamptz,
  first_seen_at         timestamptz default now(),
  updated_at            timestamptz default now(),
  removed_at            timestamptz,            -- LMS에서 사라지면 기록
  unique (user_id, canvas_assignment_id)
);
create index on lms_assignments (user_id, due_at);

create table lms_module_items (
  id                uuid primary key default gen_random_uuid(),
  canvas_course_id  bigint not null,
  canvas_item_id    bigint not null unique,
  module_name       text,                       -- 예: 8주차
  title             text not null,              -- 예: 08 - Decision Trees
  item_type         text,                       -- ExternalTool, Assignment, Quiz, Page ...
  html_url          text,                       -- LMS 바로가기
  first_seen_at     timestamptz default now()
);
create index on lms_module_items (canvas_course_id, first_seen_at);

-- 새 자료 알림에서 올린 파일을 해당 주차학습 항목에 연결 (files가 먼저 생성되므로 여기서 추가)
alter table files add column lms_module_item_id uuid references lms_module_items(id) on delete set null;

create table lms_announcements (
  id                 uuid primary key default gen_random_uuid(),
  canvas_course_id   bigint not null,
  canvas_topic_id    bigint not null unique,
  title              text not null,
  message            text,
  posted_at          timestamptz,
  attachment_count   smallint default 0,
  category           announcement_category,     -- null이면 아직 분류 전
  opportunity_id     uuid references opportunities(id) on delete set null,  -- 기회성 공지면 연결
  classified_run_id  uuid references agent_runs(id) on delete set null,
  first_seen_at      timestamptz default now()
);
create index on lms_announcements (canvas_course_id, posted_at);

-- =========================================================
-- 8. 강의계획서
-- =========================================================
create table syllabi (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references profiles(id) on delete cascade,
  lms_course_id  uuid references lms_courses(id) on delete set null,   -- LMS 과목 연결
  file_id      uuid references files(id) on delete set null,
  course_name  text,
  semester     text,                            -- 예: 2026-2
  created_at   timestamptz default now()
);
create unique index on syllabi (lms_course_id) where lms_course_id is not null;   -- 과목당 계획서 1개

create table syllabus_items (
  id            uuid primary key default gen_random_uuid(),
  syllabus_id   uuid not null references syllabi(id) on delete cascade,
  item_type     syllabus_item_type not null,
  title         text not null,
  starts_at     timestamptz,
  is_confirmed  boolean default false           -- 사용자 확인 후 등록
);

-- =========================================================
-- 9. 실행 (준비 일정 · 플래너 · 캘린더)
-- =========================================================
create table prep_plans (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references profiles(id) on delete cascade,
  opportunity_id  uuid not null references opportunities(id) on delete cascade,
  agent_run_id    uuid references agent_runs(id) on delete set null,
  created_at      timestamptz default now(),
  unique (user_id, opportunity_id)
);

create table planner_tasks (
  id                   uuid primary key default gen_random_uuid(),
  user_id              uuid not null references profiles(id) on delete cascade,
  source               task_source not null,
  prep_plan_id         uuid references prep_plans(id) on delete cascade,
  syllabus_item_id     uuid references syllabus_items(id) on delete cascade,
  lms_assignment_id    uuid references lms_assignments(id) on delete cascade,
  lms_announcement_id  uuid references lms_announcements(id) on delete cascade,
  document_id          uuid references opportunity_documents(id) on delete set null,
  title                text not null,
  due_date             date not null,
  is_done              boolean default false,   -- LMS 과제는 제출 시 자동 완료
  done_at              timestamptz,
  sort_order           int default 0,
  created_at           timestamptz default now()
);
create index on planner_tasks (user_id, due_date);

create table calendar_events (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references profiles(id) on delete cascade,
  provider           calendar_provider not null,
  opportunity_id     uuid references opportunities(id) on delete cascade,
  syllabus_item_id   uuid references syllabus_items(id) on delete cascade,
  lms_assignment_id  uuid references lms_assignments(id) on delete cascade,
  external_event_id  text,                      -- Google 이벤트 ID, ics는 UID
  title              text not null,
  starts_at          timestamptz not null,
  all_day            boolean default true,
  synced_at          timestamptz default now(),
  check (num_nonnulls(opportunity_id, syllabus_item_id, lms_assignment_id) = 1)
);
create unique index on calendar_events (user_id, provider, opportunity_id)    where opportunity_id    is not null;
create unique index on calendar_events (user_id, provider, syllabus_item_id)  where syllabus_item_id  is not null;
create unique index on calendar_events (user_id, provider, lms_assignment_id) where lms_assignment_id is not null;

-- =========================================================
-- 10. 강의자료 요약 · 번역
-- =========================================================
create table materials (
  file_id          uuid primary key references files(id) on delete cascade,
  source_language  text,
  total_pages      int,
  page_start       int,                         -- 처리한 범위 (상한 초과 시 사용자가 선택)
  page_end         int,
  text_tokens      int,                         -- 추출 텍스트 토큰 수 (상한 판정 기준)
  vision_pages     int default 0,               -- Vision으로 처리한 스캔 페이지 수
  over_limit       boolean default false,       -- 상한 초과로 범위 선택이 필요했는지 (유료화 수요 근거)
  overall_summary  text,                        -- 전체 요약 (Markdown, DB 텍스트)
  status           job_status not null default 'pending',
  agent_run_id     uuid references agent_runs(id) on delete set null,
  created_at       timestamptz default now(),
  check (page_start is null or page_end is null or page_start <= page_end)
);

create table material_sections (
  id                        uuid primary key default gen_random_uuid(),
  file_id                   uuid not null references materials(file_id) on delete cascade,
  seq                       smallint not null,
  title                     text,                 -- 목차 제목, 감지 실패 시 "12–20쪽"
  page_start                int not null,
  page_end                  int not null,
  summary                   text,                 -- 구간 요약 (Markdown)
  translation_status        job_status,           -- null이면 번역 요청 전
  translation_path          text,                 -- 번역본 Storage 경로
  translation_requested_at  timestamptz,          -- 구간 번역 요청 시각 (유료화 수요 근거)
  translation_run_id        uuid references agent_runs(id) on delete set null,
  unique (file_id, seq),
  check (page_start <= page_end),
  check (translation_status is distinct from 'succeeded' or translation_path is not null)
);

-- =========================================================
-- 11. 알림
-- =========================================================
create table notifications (
  id                   uuid primary key default gen_random_uuid(),
  user_id              uuid not null references profiles(id) on delete cascade,
  type                 notification_type not null,
  opportunity_id       uuid references opportunities(id) on delete cascade,
  planner_task_id      uuid references planner_tasks(id) on delete cascade,
  lms_assignment_id    uuid references lms_assignments(id) on delete cascade,
  lms_module_item_id   uuid references lms_module_items(id) on delete cascade,
  lms_announcement_id  uuid references lms_announcements(id) on delete cascade,
  title                text not null,
  body                 text,
  scheduled_at         timestamptz not null,
  sent_at              timestamptz,
  status               job_status not null default 'pending',
  created_at           timestamptz default now(),
  unique nulls not distinct (user_id, type, opportunity_id, planner_task_id,
                             lms_assignment_id, lms_module_item_id, lms_announcement_id)  -- 중복 발송 방지
);
create index on notifications (status, scheduled_at);
