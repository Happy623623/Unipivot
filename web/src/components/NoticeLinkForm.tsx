import type { RefObject } from "react";
import Button from "@/components/Button";

export interface LinkProblem {
  tone: "error" | "info";
  text: string;
}

// 학교 공지 링크를 붙이는 자리(B안). 주소는 화면이 들고 있어서 실패해도 지워지지 않는다(고쳐서 다시 붙인다)
export default function NoticeLinkForm({
  url,
  onUrlChange,
  onSubmit,
  problem,
  inputRef,
}: {
  url: string;
  onUrlChange: (url: string) => void;
  onSubmit: () => void;
  problem: LinkProblem | null;
  inputRef: RefObject<HTMLInputElement | null>;
}) {
  return (
    <section className="rounded-[18px] border border-[#e5e7eb] bg-white p-6 max-[760px]:p-5">
      <h2 className="text-[18px] font-bold">학교 공지 링크로 가져오기</h2>
      <p className="mt-1 text-[13px] leading-5 text-[#667085]">
        한양대 공지사항에서 공지 글을 열고 그 주소를 붙여 주세요. 그 공지 하나만 읽어 와요.
      </p>
      {/* 주소창에서 "www.hanyang.ac.kr/…"만 복사해도 서버가 받는다. 브라우저의 주소 검사는 끄고 서버 문구를 보여 준다 */}
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
        className="mt-4 flex gap-2 max-[760px]:flex-col"
      >
        <label htmlFor="notice-link" className="sr-only">
          공지 글 주소
        </label>
        <input
          ref={inputRef}
          id="notice-link"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          value={url}
          onChange={(event) => onUrlChange(event.target.value)}
          placeholder="https://www.hanyang.ac.kr/notice/url/…"
          aria-invalid={problem?.tone === "error" || undefined}
          aria-describedby={problem ? "notice-link-problem notice-link-help" : "notice-link-help"}
          className="h-[42px] min-w-0 flex-1 rounded-[10px] border border-[#e5e7eb] px-3 text-[14px] outline-none focus:border-[#4f6ef7] aria-invalid:border-[#d92d20] max-[760px]:flex-none"
        />
        <Button type="submit" disabled={!url.trim()}>
          가져오기
        </Button>
      </form>
      {problem && (
        <p
          id="notice-link-problem"
          role={problem.tone === "error" ? "alert" : "status"}
          className={`mt-2 text-[13px] leading-5 ${problem.tone === "error" ? "text-[#d92d20]" : "text-[#7a4f00]"}`}
        >
          {problem.text}
        </p>
      )}
      <p id="notice-link-help" className="mt-3 text-[12px] leading-5 text-[#667085]">
        가져온 공지는 다른 학생의 피드에도 보여요. 서울캠퍼스 공지는 가져오지 않고, 하루 10개까지 가져올 수 있어요.
      </p>
    </section>
  );
}
