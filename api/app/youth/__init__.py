"""온통청년 청년정책 수집 (PRD F-11). 받기(client), 변환(convert, regions), 저장(importer), 명령(cli).

도구 이름은 실행 로그(tool_calls.tool_name)와 공고 상세의 처리 과정이 같이 쓴다.
"""

FETCH_TOOL = "fetch_youth_policies"  # 온통청년에서 정책 목록 받기
BUILD_TOOL = "build_youth_requirements"  # 가져올 정책을 골라 요건을 만들고 저장하기
