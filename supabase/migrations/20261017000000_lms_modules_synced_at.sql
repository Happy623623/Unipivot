-- F-52: 주차 항목을 그 과목에서 처음 받았는지 기록한다.
-- 연결하고 처음 받으면 한 학기 분량(녹화 87건)이 모두 "새 항목"이라 알림을 보내지 않는다.
-- 항목이 0건인 과목이 흔해서(녹화 6과목 중 2과목) "표에 행이 있는지"로는 가릴 수 없다.
alter table lms_courses add column modules_synced_at timestamptz;

comment on column lms_courses.modules_synced_at is
  '주차 항목을 처음 받은 시각. null이면 아직 안 받았다 — 그 첫 수집은 새 자료 알림을 보내지 않는다';
