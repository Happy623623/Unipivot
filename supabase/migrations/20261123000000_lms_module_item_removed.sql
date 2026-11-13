-- =========================================================
-- 주차 항목이 LearningX에서 사라진 때(lms_module_items.removed_at) — 사용자 피드백 2①(2026-11-23)
-- 교수가 지우거나 다시 만든 항목도 표에 남아 자료 탭에 보였고, 'LMS에서 열기'가 LearningX의 없는 주소로 갔다.
-- 그 과목의 주차 목록을 끝까지 받은 동기화가 목록에 없던 항목에 찍고, 다시 나타나면 지운다(과제 removed_at과 같다).
-- 행은 지우지 않는다(알림·내가 올린 강의자료가 그 항목을 가리킨다). 더하기만 하는 변경이라 옛 코드도 그대로 돈다.
-- 여러 번 돌려도 같다 — SQL Editor로 먼저 넣고 나중에 db push를 해도 된다.
-- =========================================================

alter table lms_module_items add column if not exists removed_at timestamptz;

comment on column lms_module_items.removed_at is
  'LearningX 주차 목록에서 사라진 때. null이면 아직 있다. 다시 나타나면 null로 돌린다';
