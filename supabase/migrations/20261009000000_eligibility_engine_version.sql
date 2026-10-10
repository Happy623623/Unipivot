-- 판정 엔진 버전 (S1-5): 판정 규칙·문구를 바꾸면 app/eligibility의 ENGINE_VERSION을 올린다.
-- 버전이 다른 판정은 낡은 결과로 보고, 피드를 읽을 때 다시 계산한다(requirements_version과 같은 방식).
alter table eligibility_results
  add column engine_version int not null default 1;   -- 어느 판정 엔진 버전으로 판정했는지
