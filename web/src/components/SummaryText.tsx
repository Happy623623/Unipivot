import type { ReactNode } from "react";

// 굵게(**…**)는 글자만 남긴다(모델이 목록에 "- **개념**: …"처럼 자주 쓴다)
function plain(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, "$1").replace(/__(.+?)__/g, "$1");
}

// 요약 Markdown(모델이 쓴 글)을 그린다. 제목(#)·목록(-·*·1.)·문단만 다루고 HTML로 넣지 않는다(글 그대로 그린다)
export default function SummaryText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length === 0) return;
    blocks.push(
      <ul key={`list-${blocks.length}`} className="mt-2 list-disc space-y-1 pl-5 text-[13px] leading-5 text-[#344054]">
        {list.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>,
    );
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (/^([-*•]|\d+[.)])\s+/.test(line)) {
      list.push(plain(line.replace(/^([-*•]|\d+[.)])\s+/, "")));
      continue;
    }
    flush();
    if (/^#{1,6}\s+/.test(line)) {
      blocks.push(
        <h3 key={`h-${blocks.length}`} className="mt-4 text-[14px] font-semibold first:mt-0">
          {plain(line.replace(/^#{1,6}\s+/, ""))}
        </h3>,
      );
    } else {
      blocks.push(
        <p key={`p-${blocks.length}`} className="mt-2 text-[13px] leading-5 text-[#344054]">
          {plain(line)}
        </p>,
      );
    }
  }
  flush();
  return <div>{blocks}</div>;
}
