-- 마이그레이션을 모두 적용한 뒤 CI에서 돌리는 스키마 점검. 걸리면 오류로 끝난다.
do $$
declare bad text;
begin
  -- 1. RLS가 꺼진 public 테이블
  select string_agg(relname, ', ') into bad
  from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r' and not relrowsecurity;
  if bad is not null then raise exception 'RLS가 꺼진 테이블: %', bad; end if;

  -- 2. 인덱스가 없는 FK (인덱스 앞쪽 열이 FK 열과 같아야 함. "FK열 IS NOT NULL" 부분 인덱스는 인정)
  select string_agg(format('%s(%s)', c.conrelid::regclass, a.attname), ', ') into bad
  from pg_constraint c
  join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
  where c.contype = 'f' and c.connamespace = 'public'::regnamespace
    and not exists (
      select 1 from pg_index i
      where i.indrelid = c.conrelid
        and (string_to_array(i.indkey::text, ' ')::int2[])[1:array_length(c.conkey, 1)] = c.conkey
        and (i.indpred is null
             or pg_get_expr(i.indpred, i.indrelid) = format('(%s IS NOT NULL)', quote_ident(a.attname))));
  if bad is not null then raise exception '인덱스가 없는 FK: %', bad; end if;
end $$;
