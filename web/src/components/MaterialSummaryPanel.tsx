import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, errorMessage, getMaterial, summarizeMaterial } from "@/api/client";
import Button from "@/components/Button";
import Skeleton from "@/components/Skeleton";
import SummaryText from "@/components/SummaryText";
import useAsyncData from "@/lib/useAsyncData";
import { focusIfLost } from "@/lib/useFocusHandoff";
import type { MaterialDetail } from "@/types/api";

interface MaterialSummaryPanelProps {
  fileId: string; // 부르는 쪽이 자료마다 key를 바꿔 새로 그린다(지난 자료의 상태가 남지 않게)
  onClose: () => void;
  onChange: () => void; // 요약 상태가 바뀌면 과목 상세의 자료 목록(상태 배지)을 다시 받는다
}

const FAILED = "요약하지 못했어요. 잠시 후 다시 눌러 주세요.";
const TOO_LONG = "자료가 길어서 한 번에 요약할 수 없어요. 요약할 부분만 PDF로 나눠서 올려 주세요.";
// 화면이 1분 기다려도 안 끝났다. 요약은 뒤에서 계속 돌고, 다시 열면 이어서 기다린다(알림은 오지 않는다)
const STILL_RUNNING = "요약이 오래 걸리고 있어요. 잠시 뒤 이 자료를 다시 열어 확인해 주세요.";
// 다시 눌러도 같은 결과인 실패(자료를 바꿔 올려야 한다) — "다시 요약하기"를 숨긴다
const FINAL_CODES = new Set(["MATERIAL_TOO_LONG", "PAGE_LIMIT_EXCEEDED", "UNSUPPORTED_FILE_TYPE", "NOT_FOUND"]);
export const AI_NOTICE = "요약하려고 자료의 글을 외부 AI 서비스(Google Gemini)로 보내요. 요약에만 쓰고, 탈퇴하면 요약도 지워요.";

// 강의자료 요약(F-15 축소판). 아직 요약하지 않은 자료는 열자마자 요약한다(올리면서 요약을 고른 것이다).
// 실패했거나 멈춘 자료는 "다시 요약하기"를 누른다. 상한을 넘은 자료는 나눠 올리라고 안내한다
export default function MaterialSummaryPanel({ fileId, onClose, onChange }: MaterialSummaryPanelProps) {
  const request = useAsyncData(() => getMaterial(fileId), [fileId]);
  const [material, setMaterial] = useState<MaterialDetail | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<{ text: string; final: boolean } | null>(null);
  const started = useRef(false); // 열자마자 한 번만 요약한다
  const alive = useRef(true);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    heading.current?.focus({ preventScroll: true }); // 열면 요약 칸으로(화면 읽기 프로그램이 무엇이 열렸는지 안다)
    return () => {
      alive.current = false;
    };
  }, []);

  const summarize = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const done = await summarizeMaterial(fileId);
      if (alive.current) setMaterial(done);
    } catch (caught) {
      if (!alive.current) return;
      const code = caught instanceof ApiError ? caught.code : "";
      const text = code === "MATERIAL_TOO_LONG" ? TOO_LONG : code === "RUN_TIMEOUT" ? STILL_RUNNING : errorMessage(caught, FAILED);
      setError({ text, final: FINAL_CODES.has(code) });
    } finally {
      if (alive.current) {
        setRunning(false);
        focusIfLost(() => [heading.current]); // "다시 요약하기"가 사라지면 초점이 갈 곳
      }
      onChange();
    }
  }, [fileId, onChange]);

  const shown = material ?? request.data;
  const waiting = !!shown && !error && !started.current && (shown.status === "pending" || shown.status === "running");
  useEffect(() => {
    // 아직 요약하지 않았거나 요약하던 중이면(다른 화면에서 시작) 이어서 요약한다 — 서버가 같은 실행을 돌려준다
    if (!waiting) return;
    started.current = true;
    void summarize();
  }, [waiting, summarize]);
  const busy = running || waiting; // 자동으로 시작하기 전 한 번 그릴 때도 "요약하고 있어요"로(실패 글이 깜박이지 않게)

  return (
    <aside aria-labelledby="material-summary-title" aria-busy={busy} className="rounded-2xl border border-[#cfd7ff] bg-white p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 ref={heading} tabIndex={-1} id="material-summary-title" className="text-[18px] font-semibold outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4f6ef7]">
            강의자료 요약
          </h2>
          {shown && <p className="mt-1 truncate text-[12px] text-[#667085]">{shown.file_name ?? "강의자료"}{shown.total_pages ? ` · ${shown.total_pages}쪽` : ""}</p>}
        </div>
        <button type="button" onClick={onClose} aria-label="요약 닫기" className="text-[20px] text-[#667085]">×</button>
      </div>
      {request.loading && !shown ? (
        <Skeleton className="mt-4 h-[240px] rounded-[12px]" />
      ) : !shown ? (
        <p role="status" className="mt-4 rounded-[10px] bg-[#fef2f2] p-3 text-[13px] text-[#c53030]">{request.error ?? "요약을 불러오지 못했어요."}</p>
      ) : busy ? (
        <div role="status" className="mt-4 rounded-[12px] bg-[#eef2ff] p-4 text-[13px] text-[#344054]">
          <p className="font-semibold">요약하고 있어요</p>
          <p className="mt-1">자료 길이에 따라 1분쯤 걸려요. 이 창을 닫아도 요약은 계속돼요.</p>
        </div>
      ) : shown.status === "succeeded" && shown.overall_summary ? (
        <div className="mt-4 rounded-[12px] bg-[#f7f8fa] p-4">
          <SummaryText text={shown.overall_summary} />
          <p className="mt-3 text-[11px] text-[#667085]">AI가 쓴 요약이라 틀릴 수 있어요. 시험 공부는 원문으로 확인해 주세요.</p>
        </div>
      ) : (
        <div className="mt-4">
          <p role="status" className="rounded-[10px] bg-[#fff8e1] p-3 text-[13px] text-[#b7791f]">
            {error?.text ?? (shown.over_limit ? TOO_LONG : FAILED)}
          </p>
          {!shown.over_limit && !error?.final && (
            <div className="mt-3">
              <Button secondary onClick={() => void summarize()}>다시 요약하기</Button>
            </div>
          )}
        </div>
      )}
      <p className="mt-4 text-[11px] leading-4 text-[#667085]">{AI_NOTICE}</p>
    </aside>
  );
}
