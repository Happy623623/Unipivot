import { ButtonLink } from "@/components/Button";

// 한양대 공지사항(전체) 목록. 학생이 자기 브라우저로 열어 공지를 찾는다
export const SCHOOL_NOTICE_BOARD_URL = "https://www.hanyang.ac.kr/notice_all";

// 학교 공지 링크 가져오기(B안)를 꺼 둔 동안 링크 칸 자리에 둔다(noticeClient.ts의 NOTICE_LINK_ENABLED).
// 학생이 학교 공지사항을 새 탭으로 열어 공지를 찾고, 그 화면을 캡처해 아래 업로드로 올린다 — 포스터와 같은 길이라
// 올린 학생의 피드에만 보인다. 서버는 학교 사이트에 묻지 않는다(링크는 학생 브라우저가 연다)
export default function SchoolNoticeShortcut() {
  return (
    <section className="rounded-[18px] border border-[#e5e7eb] bg-white p-6 max-md:rounded-[14px] max-md:px-4 max-md:py-[18px]">
      <h2 className="text-[18px] font-bold">학교 공지에서 가져오기</h2>
      <p className="mt-1 text-[13px] leading-5 text-[#667085]">
        한양대 공지사항에서 공지를 열어 화면을 캡처한 뒤 아래에 올려 주세요. AI가 제목, 마감일, 지원 조건을 정리해요.
      </p>
      <div className="mt-4">
        <ButtonLink
          href={SCHOOL_NOTICE_BOARD_URL}
          className="max-md:min-h-[46px] max-md:w-full max-md:justify-center"
        >
          한양대 공지사항 열기
          <span aria-hidden="true" className="ml-1">
            ↗
          </span>
        </ButtonLink>
      </div>
      <p className="mt-3 text-[12px] leading-5 text-[#667085]">
        올린 공고는 내 피드에만 보여요. 지원 조건이 첨부 파일에만 있으면 원문 확인이 필요할 수 있어요.
      </p>
    </section>
  );
}
