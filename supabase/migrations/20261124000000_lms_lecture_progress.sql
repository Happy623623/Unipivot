-- =========================================================
-- 주차학습 강의를 들었는지(lms_lecture_progress) — 학생마다·강의마다 한 줄 (2026-11-24)
-- LearningX 주차학습(동기화가 학생 토큰으로 주차학습을 한 번 열어 읽는다, 강의 항목은 열지 않는다)의
-- 녹화 강의·실시간 수업·출석 대상 학습자료와 그 학생의 완료 여부·출결·출석 마감을 둔다.
-- 과목 공통 표(lms_module_items)와 달리 사람마다 다른 값이라 user_id가 있다(과제 lms_assignments와 같다).
-- 그 과목 목록을 다시 받으면 맞춰 바꾸고, 목록에 없는 강의는 지운다. 탈퇴·과목 행이 지워지면 함께 지워진다.
-- 더하기만 하는 변경이라 옛 코드도 그대로 돈다. 여러 번 돌려도 같다 — SQL Editor로 먼저 넣고 나중에 db push를 해도 된다.
-- =========================================================

create table if not exists lms_lecture_progress (
  user_id           uuid not null references profiles(id) on delete cascade,
  lms_course_id     uuid not null references lms_courses(id) on delete cascade,
  item_key          text not null,          -- Canvas 주차 항목 번호(= LearningX module_item_id). 없으면 'lx:' || LearningX 항목 번호
  canvas_item_id    bigint,                 -- lms_module_items.canvas_item_id와 같으면 'LMS에서 열기' 주소를 잇는다
  module_name       text not null,
  title             text not null,
  kind              text not null,          -- video(녹화)·live(실시간)·material(출석 대상 학습자료)
  completed         boolean,                -- null: LearningX가 완료 여부를 알 수 없다고 했다
  attendance        text,                   -- LearningX attendance_status 그대로(attendance·late·absent·early_leave·none)
  period            text,                   -- LearningX lecture_period_status 그대로(not_open·open·late·late_after·closed)
  unlock_at         timestamptz,
  due_at            timestamptz,            -- 출석 인정 마감
  late_at           timestamptz,            -- 지각 인정 마감
  duration_seconds  int,
  position          int not null default 0, -- 주차학습 응답 순서
  checked_at        timestamptz not null,   -- 이 값을 LearningX에서 읽은 때
  primary key (user_id, item_key)
);

alter table lms_lecture_progress drop constraint if exists lms_lecture_progress_kind_chk;
alter table lms_lecture_progress add constraint lms_lecture_progress_kind_chk
  check (kind in ('video', 'live', 'material'));

create index if not exists lms_lecture_progress_course_idx on lms_lecture_progress (lms_course_id);

alter table lms_lecture_progress enable row level security;
drop policy if exists lms_lecture_progress_select_own on lms_lecture_progress;
create policy lms_lecture_progress_select_own on lms_lecture_progress
  for select using (user_id = (select auth.uid()));

-- 마지막으로 주차학습을 읽은 때(학생마다). 배치는 1시간마다, 학생이 학업 화면을 열 때는 그때마다 읽는다
alter table lms_connections add column if not exists lectures_checked_at timestamptz;

comment on table lms_lecture_progress is
  '주차학습 강의(녹화·실시간·출석 대상 학습자료)와 그 학생의 완료 여부·출결·출석 마감(LearningX에서 읽은 값)';
comment on column lms_connections.lectures_checked_at is
  '마지막으로 주차학습(LearningX)을 읽은 때. 배치 동기화는 이 시각이 1시간 넘게 지났을 때만 다시 읽는다';
