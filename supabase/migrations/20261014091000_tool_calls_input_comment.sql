-- ERD v0.9 보강: tool_calls.input에 프로필 값을 넣지 않는다는 원칙을 컬럼 주석에 남긴다.
-- 자격 판정은 코드가 하므로 프로필 값을 LLM이나 도구 입력에 보낼 이유가 없고(PRD 6장),
-- 외부로 나가는 범위와 로그에 남는 범위를 둘 다 공고 원문으로 한정한다.
-- 코드 쪽 강제는 app/agent_log.py의 scrub다. 이 주석은 사람이 읽는 기록이다.
comment on column tool_calls.input is '도구 입력. 토큰·비밀값·프로필 값은 넣지 않는다';
