-- =========================================================
-- 정기 작업 예약표(job_schedule) — 작업마다 한 줄, 키 = 다음 실행 시각 (2026-11-18)
-- 서버 안 tick(1분마다)이나 POST /internal/jobs/tick이 때가 된 줄을 조건부 갱신 한 문장으로 집는다(임대 30분).
-- 다음 차례가 DB에 있어 서버가 꺼져 있던 동안의 차례를 깨어나 한 번 따라잡고, 몇 대가 떠도 작업마다 한 번만 돈다.
-- 줄은 서버가 처음 tick할 때 넣는다(간격 작업은 바로, 날짜 작업은 다음 KST 시각) — 이 파일은 표만 만든다.
-- 사용자 데이터가 아니다. 백엔드만 읽고 쓴다(RLS를 켜고 정책을 두지 않는다).
-- 여러 번 돌려도 같다 — SQL Editor로 먼저 넣고 나중에 db push를 해도 된다.
-- =========================================================

create table if not exists job_schedule (
  name             text primary key,
  next_run_at      timestamptz not null,
  lease_until      timestamptz,
  attempts         smallint not null default 0,
  last_finished_at timestamptz,
  last_error       text
);

alter table job_schedule drop constraint if exists job_schedule_attempts_chk;
alter table job_schedule add constraint job_schedule_attempts_chk check (attempts >= 0);

alter table job_schedule enable row level security;

comment on table job_schedule is
  '정기 작업 예약표: 작업마다 한 줄(send-notifications·lms-sync·schedule-notifications·fetch-policies)';
comment on column job_schedule.next_run_at is
  '다음 차례. 끝나면 지금 이후 첫 차례(간격 작업은 끝난 시각 + 간격, 날짜 작업은 다음 KST 시각)';
comment on column job_schedule.lease_until is
  '돌리는 중이면 이 시각까지 다른 tick이 집지 못한다(집을 때 30분). null이면 쉬는 중';
comment on column job_schedule.attempts is
  '잇달아 집힌 횟수(집을 때 올리고 끝나면 0). 날짜 작업은 실패하면 30분×2^(횟수−1) 뒤로 늦춘다';
comment on column job_schedule.last_error is
  '마지막 실패 이유(가린 글, 500자). 끝나면 비운다';
