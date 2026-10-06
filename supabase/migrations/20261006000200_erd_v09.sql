-- =========================================================
-- ERD v0.8 → v0.9 마이그레이션 (멘토 피드백 반영, 2026-10-06)
-- v0.7 DDL → v0.8 마이그레이션을 적용한 DB에 이어서 실행한다.
-- 데이터가 없다는 가정에 기대지 않도록, 기존 행이 있어도 뜻이 바뀌지 않게 옮긴다.
-- =========================================================

-- 0. 공통: updated_at 자동 갱신 함수 (확장 설치 없이 Supabase·CI 모두 동작)
create or replace function public.set_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- 1. 알림: 7개 컬럼 유니크 제거 (D-3·D-1 두 번 알림을 막고 있었음). 대신 dedupe_key (7번)
do $$
declare c text;
begin
  for c in select conname from pg_constraint
           where conrelid = 'notifications'::regclass and contype = 'u' loop
    execute format('alter table notifications drop constraint %I', c);
  end loop;
end $$;

-- 2. 자주 바뀌는 enum 3개 → text + check (값 추가는 check를 지우고 다시 거는 두 줄)
alter table requirements        alter column field          type text   using field::text;
alter table eligibility_results alter column missing_fields type text[] using missing_fields::text[];
alter table agent_runs          alter column trigger_type   type text   using trigger_type::text;
alter table notifications       alter column type           type text   using type::text;
alter table user_settings       alter column muted_notification_types drop default;
alter table user_settings       alter column muted_notification_types type text[] using muted_notification_types::text[];
alter table user_settings       alter column muted_notification_types set default '{}';
drop type req_field;
drop type run_trigger;
drop type notification_type;

alter table requirements add constraint requirements_field_chk check (field in (
  'department','grade','enrollment_status','semesters_completed','credits_total','credits_last_semester',
  'gpa_total','gpa_last_semester','age','region','income_bracket','median_income_pct','welfare_status',
  'is_international','other'));
alter table eligibility_results add constraint eligibility_results_missing_fields_chk check (missing_fields <@ array[
  'department','grade','enrollment_status','semesters_completed','credits_total','credits_last_semester',
  'gpa_total','gpa_last_semester','age','region','income_bracket','median_income_pct','welfare_status',
  'is_international']::text[]);
alter table agent_runs add constraint agent_runs_trigger_type_chk check (trigger_type in (
  'batch_crawl','poster_upload','prepare','syllabus_upload','material_upload','material_translate',
  'lms_sync','notify','eval'));
alter table notifications add constraint notifications_type_chk check (type in (
  'new_eligible','new_assignment','new_material','schedule_change','task_due','deadline_soon','profile_needed'));
alter table user_settings add constraint user_settings_muted_types_chk check (muted_notification_types <@ array[
  'new_eligible','new_assignment','new_material','schedule_change','task_due','deadline_soon','profile_needed']::text[]);

-- 3. 요건: 묶음 번호(같은 번호끼리 OR, 번호끼리 AND)와 비교 기준
alter table requirements add column clause_no smallint;
-- 기존 행은 조건마다 다른 번호를 줘서 지금 뜻(모두 AND)을 지킨다. 기본값 0을 두면 전부 OR가 되므로 두지 않는다
update requirements r set clause_no = s.rn
from (select id, row_number() over (partition by opportunity_id order by created_at, id) as rn
      from requirements) s
where r.id = s.id;
alter table requirements alter column clause_no set not null;
alter table requirements add constraint requirements_clause_no_chk check (clause_no >= 1);
drop index if exists requirements_opportunity_id_idx;
create index requirements_opportunity_clause_idx on requirements (opportunity_id, clause_no);

alter table requirements add column basis text;
update requirements set basis = 'unspecified' where field = 'region'     and basis is null;
update requirements set basis = 'department'  where field = 'department' and basis is null;
alter table requirements add constraint requirements_basis_chk check (
  case field
    when 'region'     then coalesce(basis in ('resident_registration','actual_residence','high_school','guardian','unspecified'), false)
    when 'department' then coalesce(basis in ('department','college','field_group'), false)
    else basis is null
  end);

-- 4. 학과 분류: 학과 → 단과대 → 계열. 목록은 별도 seed 마이그레이션으로 넣는다
create table departments (
  name         text primary key,                -- 프로필과 요건에 쓰는 학과 이름
  college      text not null,                   -- 단과대학
  field_group  text not null,                   -- 계열 (공학·자연·인문·사회·예체능 등)
  is_active    boolean not null default true,   -- 폐지·통합된 학과는 false (목록에서 숨김)
  sort_order   int not null default 0
);
-- 프로필 학과는 목록에 있는 이름만. 목록에 없는 기존 값은 비운다
update profiles set department = null
where department is not null and department not in (select name from departments);
alter table profiles add constraint profiles_department_fkey
  foreign key (department) references departments(name) on update cascade on delete set null;

-- 5. 프로필: 유학생 여부, 소득·수급 정보 선택 동의
alter table profiles
  add column is_international        boolean,       -- null이면 미입력
  add column income_info_agreed_at   timestamptz;   -- 소득·수급 정보 수집·이용 동의(선택). 철회하면 null
-- 동의 없이 남아 있는 소득·수급 값은 먼저 비운다
update profiles set income_bracket = null, median_income_pct = null, welfare_status = null
where income_info_agreed_at is null
  and (income_bracket is not null or median_income_pct is not null or welfare_status is not null);
alter table profiles add constraint profiles_income_consent_chk check (
  income_info_agreed_at is not null
  or (income_bracket is null and median_income_pct is null and welfare_status is null));

-- 6. 공고: 판정 기준일, 원문 변경 감지, 요건 버전, 난이도 삭제(정의 전까지 컬럼을 두지 않음)
alter table opportunities
  add column eligibility_basis_date  date,                     -- null이면 마감일(KST 날짜)
  add column content_hash            text,                     -- 본문 + 첨부 추출 텍스트의 sha256
  add column requirements_version    int not null default 1,   -- 다시 추출할 때마다 1 올림
  drop column difficulty;
alter table eligibility_results
  add column requirements_version    int not null default 1;   -- 어느 요건 버전으로 판정했는지

-- 7. 알림 중복 방지 키: "{type}:{대상}:{id}[:{시점}]" 예) deadline_soon:opp:<id>:D-3
alter table notifications add column dedupe_key text;
update notifications set dedupe_key = 'legacy:' || id where dedupe_key is null;
alter table notifications alter column dedupe_key set not null;
create unique index notifications_user_dedupe_uq on notifications (user_id, dedupe_key);

-- 8. 공고 첨부파일: 학교 공지는 본문이 "첨부 참조"인 경우가 많다
create table opportunity_attachments (
  id              uuid primary key default gen_random_uuid(),
  opportunity_id  uuid not null references opportunities(id) on delete cascade,
  seq             smallint not null default 1,
  file_name       text not null,
  mime_type       text,
  source_url      text,
  storage_path    text,
  sha256          text,
  extracted_text  text,
  extract_method  text check (extract_method in ('pdf_text','hwpx_text','hwp_text','vision')),
  extract_error   text,                         -- 추출 실패 사유. 실패한 첨부가 있으면 원문 확인 필요
  extracted_at    timestamptz,
  created_at      timestamptz not null default now(),
  unique (opportunity_id, source_url)
);

-- 9. 플래너: source와 연결 대상이 맞아야 하고, 같은 과제·계획서 일정은 사용자당 할 일 1개
alter table planner_tasks add constraint planner_tasks_source_chk check (
  case source
    when 'prep_plan'        then prep_plan_id        is not null and num_nonnulls(prep_plan_id, syllabus_item_id, lms_assignment_id, lms_announcement_id) = 1
    when 'syllabus'         then syllabus_item_id    is not null and num_nonnulls(prep_plan_id, syllabus_item_id, lms_assignment_id, lms_announcement_id) = 1
    when 'lms_assignment'   then lms_assignment_id   is not null and num_nonnulls(prep_plan_id, syllabus_item_id, lms_assignment_id, lms_announcement_id) = 1
    when 'lms_announcement' then lms_announcement_id is not null and num_nonnulls(prep_plan_id, syllabus_item_id, lms_assignment_id, lms_announcement_id) = 1
    when 'manual'           then num_nonnulls(prep_plan_id, syllabus_item_id, lms_assignment_id, lms_announcement_id) = 0
  end);
alter table planner_tasks add constraint planner_tasks_document_chk check (document_id is null or source = 'prep_plan');
create unique index planner_tasks_user_assignment_uq    on planner_tasks (user_id, lms_assignment_id) where lms_assignment_id is not null;
create unique index planner_tasks_user_syllabus_item_uq on planner_tasks (user_id, syllabus_item_id)  where syllabus_item_id  is not null;

-- 10. LMS 분반 한정 공지: 저장은 하되 MVP에서는 보여주지 않는다
alter table lms_announcements add column is_section_specific boolean not null default false;

-- 11. 업로드 파일: 같은 사용자가 같은 파일을 다시 올리면 기존 행을 쓴다
create unique index files_user_upload_sha_uq on files (user_id, sha256, kind) where origin = 'upload';

-- 12. 캘린더: .ics 내려받기는 기록하지 않는다 (동기화 상태가 없고 재다운로드 때 유니크 충돌)
alter table calendar_events add constraint calendar_events_no_ics_chk check (provider <> 'ics');

-- 13. 사용 이벤트: 제품 지표 원천 (기록은 API만)
create table usage_events (
  id              bigint generated always as identity primary key,
  user_id         uuid not null references profiles(id) on delete cascade,
  event           text not null check (event in (
                    'app_open','profile_prompt_shown','profile_prompt_submitted','lms_guide_opened','lms_connected')),
  opportunity_id  uuid references opportunities(id) on delete set null,
  occurred_at     timestamptz not null default now(),
  occurred_on     date not null default ((now() at time zone 'Asia/Seoul')::date)   -- KST 날짜
);
create unique index usage_events_app_open_daily_uq on usage_events (user_id, occurred_on) where event = 'app_open';
create index usage_events_event_time_idx on usage_events (event, occurred_at);

-- 14. updated_at 자동 갱신
create trigger opportunities_set_updated_at   before update on opportunities   for each row execute function public.set_updated_at();
create trigger lms_assignments_set_updated_at before update on lms_assignments for each row execute function public.set_updated_at();
create trigger user_settings_set_updated_at   before update on user_settings   for each row execute function public.set_updated_at();

-- 15. FK 인덱스: 탈퇴(cascade)·공고 삭제·조인이 풀스캔하지 않게 모든 FK에 인덱스
--     (syllabi.lms_course_id는 기존 부분 유니크 인덱스가 대신한다)
create index profiles_department_idx               on profiles (department);
create index push_subscriptions_user_id_idx        on push_subscriptions (user_id);
create index agent_runs_user_id_idx                on agent_runs (user_id);
create index llm_calls_tool_call_id_idx            on llm_calls (tool_call_id);
create index files_lms_course_id_idx               on files (lms_course_id);
create index files_lms_module_item_id_idx          on files (lms_module_item_id);
create index opportunities_extraction_run_id_idx   on opportunities (extraction_run_id);
create index opportunities_merged_into_id_idx      on opportunities (merged_into_id);
create index opportunities_poster_file_id_idx      on opportunities (poster_file_id);
create index opportunities_uploaded_by_idx         on opportunities (uploaded_by);
create index opportunity_documents_opportunity_idx on opportunity_documents (opportunity_id);
create index opportunity_reports_reporter_id_idx   on opportunity_reports (reporter_id);
create index eligibility_results_opportunity_idx   on eligibility_results (opportunity_id);
create index lms_assignments_lms_course_id_idx     on lms_assignments (lms_course_id);
create index lms_announcements_classified_run_idx  on lms_announcements (classified_run_id);
create index lms_announcements_opportunity_id_idx  on lms_announcements (opportunity_id);
create index syllabi_file_id_idx                   on syllabi (file_id);
create index syllabi_user_id_idx                   on syllabi (user_id);
create index syllabus_items_syllabus_id_idx        on syllabus_items (syllabus_id);
create index prep_plans_agent_run_id_idx           on prep_plans (agent_run_id);
create index prep_plans_opportunity_id_idx         on prep_plans (opportunity_id);
create index planner_tasks_document_id_idx         on planner_tasks (document_id);
create index planner_tasks_lms_announcement_idx    on planner_tasks (lms_announcement_id);
create index planner_tasks_lms_assignment_idx      on planner_tasks (lms_assignment_id);
create index planner_tasks_prep_plan_id_idx        on planner_tasks (prep_plan_id);
create index planner_tasks_syllabus_item_idx       on planner_tasks (syllabus_item_id);
create index calendar_events_user_id_idx           on calendar_events (user_id);
create index calendar_events_opportunity_id_idx    on calendar_events (opportunity_id);
create index calendar_events_syllabus_item_idx     on calendar_events (syllabus_item_id);
create index calendar_events_lms_assignment_idx    on calendar_events (lms_assignment_id);
create index materials_agent_run_id_idx            on materials (agent_run_id);
create index material_sections_translation_run_idx on material_sections (translation_run_id);
create index notifications_opportunity_id_idx      on notifications (opportunity_id);
create index notifications_planner_task_id_idx     on notifications (planner_task_id);
create index notifications_lms_assignment_idx      on notifications (lms_assignment_id);
create index notifications_lms_module_item_idx     on notifications (lms_module_item_id);
create index notifications_lms_announcement_idx    on notifications (lms_announcement_id);
create index opportunity_views_opportunity_id_idx  on opportunity_views (opportunity_id);
create index usage_events_user_id_idx              on usage_events (user_id);
create index usage_events_opportunity_id_idx       on usage_events (opportunity_id);

-- 16. RLS: public의 모든 테이블에 켠다. v0.7 DDL에는 RLS 문이 없어서 Supabase Data API(anon 키)로
--     전부 읽히고 쓰일 수 있었다. 프론트는 DB를 직접 읽지 않으므로(API 명세 1장) 정책은 "읽기"만 두고
--     쓰기 정책은 만들지 않는다. 쓰기는 백엔드(테이블 소유자 연결)만 한다.
do $$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;

-- 본인 행만 (토큰·로그·출처·사용 이벤트 테이블은 정책 없음 = 아무도 직접 못 읽음)
create policy profiles_select_own            on profiles            for select using (id = (select auth.uid()));
create policy push_subscriptions_select_own  on push_subscriptions  for select using (user_id = (select auth.uid()));
create policy lms_courses_select_own         on lms_courses         for select using (user_id = (select auth.uid()));
create policy lms_assignments_select_own     on lms_assignments     for select using (user_id = (select auth.uid()));
create policy files_select_own               on files               for select using (user_id = (select auth.uid()));
create policy opportunity_reports_select_own on opportunity_reports for select using (reporter_id = (select auth.uid()));
create policy eligibility_results_select_own on eligibility_results for select using (user_id = (select auth.uid()));
create policy syllabi_select_own             on syllabi             for select using (user_id = (select auth.uid()));
create policy prep_plans_select_own          on prep_plans          for select using (user_id = (select auth.uid()));
create policy planner_tasks_select_own       on planner_tasks       for select using (user_id = (select auth.uid()));
create policy calendar_events_select_own     on calendar_events     for select using (user_id = (select auth.uid()));
create policy notifications_select_own       on notifications       for select using (user_id = (select auth.uid()));
create policy syllabus_items_select_own      on syllabus_items      for select using (
  exists (select 1 from syllabi s where s.id = syllabus_items.syllabus_id and s.user_id = (select auth.uid())));
create policy materials_select_own           on materials           for select using (
  exists (select 1 from files f where f.id = materials.file_id and f.user_id = (select auth.uid())));
create policy material_sections_select_own   on material_sections   for select using (
  exists (select 1 from files f where f.id = material_sections.file_id and f.user_id = (select auth.uid())));

-- 수강 과목 공통 데이터: 그 과목을 듣는 사용자만, 분반 한정 공지는 MVP에서 제외
create policy lms_module_items_select_enrolled on lms_module_items for select using (
  exists (select 1 from lms_courses c
          where c.user_id = (select auth.uid()) and c.canvas_course_id = lms_module_items.canvas_course_id));
create policy lms_announcements_select_enrolled on lms_announcements for select using (
  not is_section_specific
  and exists (select 1 from lms_courses c
              where c.user_id = (select auth.uid()) and c.canvas_course_id = lms_announcements.canvas_course_id));

-- 공고: 활성 공고(포스터는 올린 본인만, 과목 공지 공고는 수강생만) + 준비를 시작한 공고는 마감·숨김 뒤에도 본인에게
create policy opportunities_select_visible on opportunities for select using (
  (
    status = 'active'
    and (select auth.uid()) is not null
    and (source_type <> 'poster' or uploaded_by = (select auth.uid()))
    and (visible_canvas_course_id is null or exists (
          select 1 from lms_courses c
          where c.user_id = (select auth.uid())
            and c.canvas_course_id = opportunities.visible_canvas_course_id
            and c.is_active))
  )
  or exists (select 1 from prep_plans p
             where p.user_id = (select auth.uid()) and p.opportunity_id = opportunities.id));
-- 요건·서류·첨부는 공고를 볼 수 있으면 같이 본다 (opportunities 정책을 그대로 따름)
create policy requirements_select_visible            on requirements            for select using (
  exists (select 1 from opportunities o where o.id = requirements.opportunity_id));
create policy opportunity_documents_select_visible   on opportunity_documents   for select using (
  exists (select 1 from opportunities o where o.id = opportunity_documents.opportunity_id));
create policy opportunity_attachments_select_visible on opportunity_attachments for select using (
  exists (select 1 from opportunities o where o.id = opportunity_attachments.opportunity_id));

-- 학과 목록: 로그인한 사용자 누구나
create policy departments_select_signed_in on departments for select using ((select auth.uid()) is not null);

-- 17. 주석
comment on column requirements.clause_no               is '같은 번호끼리 OR, 서로 다른 번호끼리 AND. 1부터';
comment on column requirements.basis                   is 'region: resident_registration·actual_residence·high_school·guardian·unspecified / department: department·college·field_group';
comment on column opportunities.eligibility_basis_date is '만 나이·학년·재학 상태를 따지는 기준일. null이면 마감일(KST)';
comment on column notifications.dedupe_key             is '{type}:{대상}:{id}[:{시점}]. 사용자당 같은 키 1행. 마감이 바뀌면 pending 행의 scheduled_at만 고친다';
comment on column oauth_tokens.access_token            is '백엔드가 Fernet으로 암호화한 값. 키는 DB 밖(환경변수)';
comment on column oauth_tokens.refresh_token           is '백엔드가 Fernet으로 암호화한 값. 키는 DB 밖(환경변수)';
comment on column lms_connections.access_token         is '백엔드가 Fernet으로 암호화한 값. 화면에는 token_last4만';
comment on column profiles.department                  is 'departments.name. 목록에 있는 학과만';
comment on column lms_courses.name                     is '예: 202620HY23525_선형대수 (포털 과목번호 23525와 같은 과목)';
