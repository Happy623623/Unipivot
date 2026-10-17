-- 연 소득·취업 상태 (2026-10-17): 온통청년 청년정책의 소득 금액(earnMinAmt·earnMaxAmt)과
-- 취업 요건(jobCd)은 이미 구조화되어 들어오는데 비교할 프로필 칸이 없어 'other'(원문 확인 필요)로
-- 떨어지고 있었다. 측정 결과 막힌 공고 134건 중 소득이 47건, 취업 상태가 39건에 걸려 있다.
--
-- annual_income 은 본인 연 소득이고 단위는 만 원이다. 가구 합산·기준 중위소득은 기존
-- median_income_pct 가 맡으므로 변환기는 덧글이 그런 기준을 가리키면 금액 비교를 하지 않는다.
-- 소득은 선택 동의(income_info_agreed_at) 범위이므로 기존 소득 칸과 같은 제약을 받는다.
-- job_status 는 민감정보가 아니라 동의 제약을 걸지 않는다.
-- 값 목록은 enum 대신 text + check로 둔다(ERD 6장: 값을 더할 때는 check를 지우고 다시 건다).

alter table profiles add column annual_income smallint;  -- 만 원 단위. 0~32767만 원(약 3.2억)
alter table profiles add constraint profiles_annual_income_chk
  check (annual_income is null or annual_income >= 0);

alter table profiles add column job_status text;
alter table profiles add constraint profiles_job_status_chk
  check (job_status in ('employed','self_employed','unemployed','freelancer',
                        'daily_worker','founder','short_term','farmer'));

-- 소득 선택 동의 제약에 annual_income 을 더한다 (제약은 지우고 다시 건다)
alter table profiles drop constraint profiles_income_consent_chk;
update profiles set annual_income = null where income_info_agreed_at is null;
alter table profiles add constraint profiles_income_consent_chk check (
  income_info_agreed_at is not null
  or (income_bracket is null and median_income_pct is null
      and annual_income is null and welfare_status is null));

alter table requirements drop constraint requirements_field_chk;
alter table requirements add constraint requirements_field_chk check (field in (
  'department','grade','enrollment_status','semesters_completed','credits_total','credits_last_semester',
  'gpa_total','gpa_last_semester','age','region','income_bracket','median_income_pct','welfare_status',
  'is_international','degree_program','annual_income','job_status','other'));

alter table eligibility_results drop constraint eligibility_results_missing_fields_chk;
alter table eligibility_results add constraint eligibility_results_missing_fields_chk check (missing_fields <@ array[
  'department','grade','enrollment_status','semesters_completed','credits_total','credits_last_semester',
  'gpa_total','gpa_last_semester','age','region','income_bracket','median_income_pct','welfare_status',
  'is_international','degree_program','annual_income','job_status']::text[]);
