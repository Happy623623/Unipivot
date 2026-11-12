-- =========================================================
-- 과목 공지 큐 임대(lease) — 다시 집을 시각과 시도 횟수 (2026-11-14)
-- 동기화가 분류·공고 만들기를 할 공지를 집을 때 그 자리에서 attempts를 올리고 retry_at을 2시간 뒤로 민다.
-- 그동안 다른 동기화는 같은 공지를 집지 않는다. 실패하면 retry_at을 30분·1시간·2시간·4시간 뒤로 늦추고,
-- 5번 집혔는데도 끝내지 못한 공지는 줄에서 빠진다(학생은 LMS에서 원문을 본다).
-- 늘 실패하는 공지가 큐 앞자리를 차지하던 것과 같은 공지를 두 동기화가 함께 처리하던 것을 막는다.
-- 여러 번 돌려도 같다 — SQL Editor로 먼저 넣고 나중에 db push를 해도 된다.
-- =========================================================

alter table lms_announcements add column if not exists retry_at timestamptz;
alter table lms_announcements add column if not exists attempts smallint not null default 0;

alter table lms_announcements drop constraint if exists lms_announcements_attempts_chk;
alter table lms_announcements add constraint lms_announcements_attempts_chk check (attempts >= 0);

comment on column lms_announcements.retry_at is
  '과목 공지 큐: 이 시각부터 다시 집는다(집을 때 2시간 임대, 실패하면 30분×2^(시도−1)). null이면 바로 집는다';
comment on column lms_announcements.attempts is
  '과목 공지 큐: 분류·공고 만들기로 집힌 횟수(집을 때 올린다). 5면 줄에서 빠진다';
