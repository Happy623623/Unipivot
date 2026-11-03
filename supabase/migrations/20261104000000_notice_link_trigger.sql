-- =========================================================
-- 학교 공지 링크 가져오기(B안, PRD F-10) — 실행 종류 notice_link (2026-11-04)
-- 학생이 붙인 공지 링크 한 건을 읽는 실행(agent_runs.trigger_type = notice_link, user_id = 그 학생).
-- 요건 추출은 A안 가져오기처럼 batch_crawl 실행(user_id 없음)으로 따로 남는다.
-- 여러 번 돌려도 같다 — SQL Editor로 먼저 넣고 나중에 db push를 해도 된다.
-- =========================================================

alter table agent_runs drop constraint if exists agent_runs_trigger_type_chk;
alter table agent_runs add constraint agent_runs_trigger_type_chk check (trigger_type in (
  'batch_crawl','poster_upload','prepare','syllabus_upload','material_upload','material_translate',
  'lms_sync','notify','eval','notice_link'));
