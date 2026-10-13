-- 관심 공고 (2026-10-13, docs/관심공고_구현.md, PRD F-45): 공고마다 내 표시 하나.
-- 값: interested 관심, not_interested 관심 없음. 표시가 없으면 행이 없다.
-- 관심 없음 공고는 피드·홈 요약 숫자·알림(새 공고·마감 임박)에서 뺀다. 값 목록은 enum 대신 text + check(ERD 6장).

create table opportunity_marks (
  user_id         uuid not null references profiles(id) on delete cascade,
  opportunity_id  uuid not null references opportunities(id) on delete cascade,
  mark            text not null,
  marked_at       timestamptz not null default now(),   -- 표시가 바뀐 시각. 같은 표시를 다시 고르면 그대로
  primary key (user_id, opportunity_id),
  constraint opportunity_marks_mark_chk check (mark in ('interested','not_interested'))
);

-- user_id는 기본 키 앞쪽 열이라 따로 인덱스가 필요 없다
create index opportunity_marks_opportunity_id_idx on opportunity_marks (opportunity_id);

-- RLS: 본인 행만 읽기(쓰기는 백엔드). ERD 8장
alter table opportunity_marks enable row level security;
create policy opportunity_marks_select_own on opportunity_marks for select using (user_id = (select auth.uid()));
