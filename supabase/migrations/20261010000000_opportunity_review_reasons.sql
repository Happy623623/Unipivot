-- 원문 확인 필요 이유 (S1-6b, F-42). 요건 추출이 needs_review를 켠 이유를 남겨 공고 상세에 보인다
alter table opportunities
  add column review_reasons text[] not null default '{}';   -- 추출할 때마다 새 값으로 바꾼다. 이유가 없으면 빈 배열
