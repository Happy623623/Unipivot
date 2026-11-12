-- =========================================================
-- 실행 트리(오케스트레이션 O1) — agent_runs.parent_run_id·root_run_id (2026-11-17)
-- 흐름 하나가 뿌리 실행이고, 그 안에서 엔진을 한 번 부르는 일이 자식 실행이다. 뿌리는 두 칸 모두 null이다.
-- 지금 자식은 둘: LMS 동기화 안의 기회성 공지 요건 추출, 학교 공지 링크(B안)의 요건 추출.
-- 자식은 부모의 trigger_type·scenario_code를 그대로 받고 user_id는 비운다(결과를 여러 학생이 보는 엔진).
-- 뿌리의 cost_usd에는 자식 비용이 들어 있다 — 성공률·응답시간은 뿌리(parent_run_id is null)만 세고,
-- 비용은 llm_calls를 더하거나 뿌리의 cost_usd만 더한다(두 층을 함께 더하면 두 번 센다).
-- 부모가 지워져도 자식은 남는다(on delete set null) — 공고의 extraction_run_id가 자식을 가리킨다.
-- 여러 번 돌려도 같다 — SQL Editor로 먼저 넣고 나중에 db push를 해도 된다.
-- =========================================================

alter table agent_runs add column if not exists parent_run_id uuid
  references agent_runs(id) on delete set null;
alter table agent_runs add column if not exists root_run_id uuid
  references agent_runs(id) on delete set null;

create index if not exists agent_runs_parent_run_id_idx on agent_runs (parent_run_id)
  where parent_run_id is not null;
create index if not exists agent_runs_root_run_id_idx on agent_runs (root_run_id)
  where root_run_id is not null;

comment on column agent_runs.parent_run_id is
  '실행 트리: 이 실행을 연 실행(엔진 실행이면 흐름 실행). 뿌리면 null';
comment on column agent_runs.root_run_id is
  '실행 트리: 뿌리 실행(흐름). 뿌리 자신은 null. 성공률·응답시간은 뿌리만 센다';
