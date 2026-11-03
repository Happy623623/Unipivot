"""학교 공지 링크 가져오기(B안, PRD F-10). API 명세 6장 `POST /notices/link` · 11장 결과 `notice_link`."""

from typing import Literal

from pydantic import BaseModel, Field

# 학생의 실행(trigger notice_link)에 남는 단계. 요건 추출은 따로 실행(batch_crawl)으로 남는다(app/crawl/service.py)
PAGE_TOOL = "fetch_notice_page"
FILES_TOOL = "fetch_notice_files"
IMPORT_TOOL = "import_notice"
# 처리 과정(실행 조회)에 보이는 단계 이름. 화면이 첫 폴링 전에 보여 주는 이름과 같게 둔다
STEP_LABELS = {
    PAGE_TOOL: "공지 페이지 읽기",
    FILES_TOOL: "첨부 파일 받기",
    IMPORT_TOOL: "AI로 지원 자격 정리",
}


class NoticeLinkRequest(BaseModel):
    url: str = Field(max_length=4000)  # 공지 글 주소. 모양 검사는 서버가 한다(2000자 넘으면 422)


class NoticeLinkStarted(BaseModel):
    # running: 읽기 시작했다(202) 또는 같은 공지를 이미 읽고 있다(200). existing: 이미 가져온 공지(200)
    status: Literal["running", "existing"]
    run_id: str | None  # running일 때 GET /runs/{run_id}로 진행을 본다
    opportunity_id: str | None  # existing일 때 그 공고


class NoticeLinkResult(BaseModel):
    kind: Literal["notice_link"] = "notice_link"
    opportunity_id: str
    title: str
    # new 새로 가져옴 · existing 그새 다른 학생이 가져옴 · unchanged·updated 이미 있던 글(내용이 같음·바뀜)
    status: Literal["new", "updated", "unchanged", "existing"]
