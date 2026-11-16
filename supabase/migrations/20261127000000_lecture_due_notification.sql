-- =========================================================
-- 출석 마감 하루 전 알림(lecture_due, F-55 뒤) — 주차학습 강의를 아직 안 들었으면 출석 인정 마감 전날 KST 09:00 (2026-11-27)
-- 알림이 과목의 강의 탭으로 가도록 notifications.lms_course_id(내 과목 행)를 더하고, 알림 종류·끈 종류 check에
-- 'lecture_due'를 더한다. 키는 lecture_due:{lms_course_id}:{마감 날짜(KST)} — 학생 × 과목 × 마감 날짜마다 한 행.
-- 더하기만 하는 변경이라 옛 코드도 그대로 돈다. 여러 번 돌려도 같다 — SQL Editor로 먼저 넣고 나중에 db push를 해도 된다.
-- =========================================================

alter table notifications add column if not exists lms_course_id uuid
  references lms_courses(id) on delete cascade;
create index if not exists notifications_lms_course_idx on notifications (lms_course_id);

alter table notifications drop constraint if exists notifications_type_chk;
alter table notifications add constraint notifications_type_chk check (type in (
  'new_eligible','new_assignment','new_material','schedule_change','task_due','deadline_soon','profile_needed',
  'lecture_due'));

alter table user_settings drop constraint if exists user_settings_muted_types_chk;
alter table user_settings add constraint user_settings_muted_types_chk check (muted_notification_types <@ array[
  'new_eligible','new_assignment','new_material','schedule_change','task_due','deadline_soon','profile_needed',
  'lecture_due']::text[]);

comment on column notifications.lms_course_id is
  '과목으로 가는 알림(출석 마감 lecture_due)의 내 과목 행. 누르면 그 과목의 강의 탭으로 간다';
