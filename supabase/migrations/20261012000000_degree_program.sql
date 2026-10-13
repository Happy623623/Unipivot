-- 학위과정 (2026-10-12, docs/학위과정_구현.md): 대학원생 대상 공고를 판정한다.
-- 프로필에 지금 다니는(졸업했으면 마지막으로 다닌) 학위과정을 두고, 요건 항목에 degree_program을 더한다.
-- 값: bachelor 학부, master 석사, doctoral 박사, integrated 석박사통합. null이면 미입력이다.
-- 값 목록은 enum 대신 text + check로 둔다(ERD 6장: 값을 더할 때는 check를 지우고 다시 건다).

alter table profiles add column degree_program text;
alter table profiles add constraint profiles_degree_program_chk
  check (degree_program in ('bachelor','master','doctoral','integrated'));

alter table requirements drop constraint requirements_field_chk;
alter table requirements add constraint requirements_field_chk check (field in (
  'department','grade','enrollment_status','semesters_completed','credits_total','credits_last_semester',
  'gpa_total','gpa_last_semester','age','region','income_bracket','median_income_pct','welfare_status',
  'is_international','degree_program','other'));

alter table eligibility_results drop constraint eligibility_results_missing_fields_chk;
alter table eligibility_results add constraint eligibility_results_missing_fields_chk check (missing_fields <@ array[
  'department','grade','enrollment_status','semesters_completed','credits_total','credits_last_semester',
  'gpa_total','gpa_last_semester','age','region','income_bracket','median_income_pct','welfare_status',
  'is_international','degree_program']::text[]);
