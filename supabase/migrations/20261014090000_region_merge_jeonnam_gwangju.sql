-- 2026-07-01 행정구역 개편: 광주광역시 + 전라남도 → 전남광주통합특별시
-- 통합 전 이름으로 저장한 프로필 거주지역을 통합 이름으로 옮긴다. 판정 엔진(api/app/eligibility/regions.py)과
-- 프로필 스키마(api/app/schemas/me.py RegionSido)가 통합 이름만 정식으로 받으므로, 옮기지 않으면
-- 해당 사용자가 프로필을 저장할 때 검증에서 막힌다.
-- 시·군·구는 두 곳에서 이름이 겹치지 않아(광주 5개 구 vs 전남 시·군) 그대로 둔다.
update profiles
   set region_sido = '전남광주통합특별시'
 where region_sido in ('광주광역시', '전라남도');

-- 저장된 판정은 engine_version이 낡아져 피드를 읽을 때 다시 계산된다(app/eligibility/__init__.py).

