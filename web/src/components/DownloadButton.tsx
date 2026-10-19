import { useState } from "react";
import { downloadDocument, errorMessage } from "@/api/client";

interface DownloadButtonProps {
  fileId: string;
  fileName: string; // 화면 읽기 프로그램에 무엇을 받는지 알린다
  onError: (message: string) => void;
  compact?: boolean; // 공지 첨부 줄처럼 글자만 있는 작은 자리
}

const FAILED = "파일을 받지 못했어요. 잠시 후 다시 눌러 주세요.";

// 문서함 파일 받기 (F-44). 누를 때마다 5분짜리 받기 주소를 새로 받아 그 주소에서 파일을 받아 저장한다(화면은
// 그대로). 받는 동안은 눌러도 지나간다 — disabled로 막으면 키보드 초점이 버튼에서 빠져 문서 맨 위로 튄다
export default function DownloadButton({ fileId, fileName, onError, compact = false }: DownloadButtonProps) {
  const [busy, setBusy] = useState(false);
  const download = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await downloadDocument(fileId, fileName);
    } catch (error) {
      onError(errorMessage(error, FAILED));
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      onClick={download}
      aria-disabled={busy}
      aria-busy={busy}
      aria-label={`${fileName} ${busy ? "받는 중" : "받기"}`}
      className={
        compact
          ? "min-h-6 shrink-0 px-1 font-semibold text-[#4f6ef7] hover:text-[#425fe0] aria-disabled:cursor-wait aria-disabled:text-[#a0a4ab]"
          : "h-[34px] shrink-0 rounded-[10px] border border-[#e5e7eb] bg-white px-3 text-[13px] font-semibold text-[#181a20] transition hover:bg-[#f7f8fa] active:scale-[0.98] aria-disabled:cursor-wait aria-disabled:text-[#a0a4ab]"
      }
    >
      {busy ? "받는 중…" : "받기"}
    </button>
  );
}
