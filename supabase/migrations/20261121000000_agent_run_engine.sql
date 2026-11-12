-- =========================================================
-- 엔진 도장(오케스트레이션 O2) — agent_runs.engine·engine_version·model·review_codes (2026-11-21)
-- 엔진 한 번인 실행에 엔진 등록부(api/app/engines/registry.py)의 엔진 이름과 버전을 남긴다.
-- 엔진이 여럿인 흐름(LMS 동기화·학교 공지 링크)은 뿌리에 engine이 없고 자식 실행마다 있다.
-- 엔진 하나뿐인 흐름(포스터·계획서·강의자료·준비하기·A안 공지 추출)은 뿌리가 곧 엔진 한 번이라 뿌리에 있다.
-- model은 그 실행에서 마지막으로 부른 모델, review_codes는 원문 확인 이유 코드(api/app/engines/review.py)다.
-- 화면 문구(opportunities.review_reasons)는 그대로이고, 코드는 엔진별 지표·평가가 센다.
-- 이 마이그레이션 전의 실행은 engine이 null이라 엔진별 지표에 들지 않는다.
-- 여러 번 돌려도 같다 — SQL Editor로 먼저 넣고 나중에 db push를 해도 된다.
-- =========================================================

alter table agent_runs add column if not exists engine text;
alter table agent_runs add column if not exists engine_version int;
alter table agent_runs add column if not exists model text;
alter table agent_runs add column if not exists review_codes text[] not null default '{}';

-- 엔진 이름과 버전은 함께 있거나 함께 없다
alter table agent_runs drop constraint if exists agent_runs_engine_version_check;
alter table agent_runs add constraint agent_runs_engine_version_check
  check ((engine is null) = (engine_version is null));

create index if not exists agent_runs_engine_idx on agent_runs (engine, engine_version, started_at)
  where engine is not null;

comment on column agent_runs.engine is
  '엔진 등록부 id(예: extract.requirements). 엔진 한 번인 실행에만 있고 엔진이 여럿인 흐름의 뿌리는 null';
comment on column agent_runs.engine_version is
  '그 엔진의 버전(등록부). 프롬프트·도구·검증 규칙·상한이 바뀌면 오른다. engine과 함께 있다';
comment on column agent_runs.model is
  '이 실행에서 마지막으로 부른 모델(자기 llm_calls 기준). 모델을 부르지 않았으면 null';
comment on column agent_runs.review_codes is
  '원문 확인 이유 코드(NO_SUBMISSION·AMBIGUOUS 등). 같은 코드는 한 번만. 화면 문구는 review_reasons';
