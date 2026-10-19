-- F-54: 공지마다 첨부 목록을 남긴다. 과목 상세의 공지 탭이 첨부마다 이름·크기와
-- 저장 상태(저장됨·커서 저장하지 않음·저장 전)를 보여 준다.
--
-- 한 원소는 {"id": Canvas 첨부 번호, "name": 이름, "size": 바이트, "content_type": 형식}이다.
-- **첨부 주소(url)는 넣지 않는다** — 주소의 verifier만 있으면 로그인 없이 받을 수 있다(10/19 녹화).
-- 표가 과목 공통이라 저장 상태는 여기 두지 않는다. 학생마다 files(origin = lms_attachment,
-- external_ref = 첨부 번호)가 있는지로 본다.
alter table lms_announcements add column attachments jsonb not null default '[]'::jsonb;

alter table lms_announcements add constraint lms_announcements_attachments_chk
  check (jsonb_typeof(attachments) = 'array');

comment on column lms_announcements.attachments is
  '첨부 목록 [{id, name, size, content_type}]. 주소(verifier)는 넣지 않는다 (F-54)';
