import { useEffect, useRef, useState } from "react";
import { ApiError, errorMessage, getPosterUrl } from "@/api/client";
import Button, { ButtonLink } from "@/components/Button";
import Modal from "@/components/Modal";
import type { PosterKind } from "@/types/api";

interface PosterOriginalProps {
  opportunityId: string;
  kind: PosterKind;
  title: string;
  onClose: () => void;
}

// PDF 링크를 내리는 시각. 서버 주소는 5분이라, 시계가 조금 어긋나도 열리지 않는 링크를 누르지 않게 먼저 내린다
const LINK_MS = 4.5 * 60 * 1000;
const FAILED = "포스터를 불러오지 못했어요. 잠시 후 다시 불러와 주세요.";

type State =
  | { status: "loading" }
  | { status: "ready"; url: string }
  | { status: "expired" }
  | { status: "error"; message: string; retry: boolean };

// 내가 올린 포스터의 원문 보기 창(W6). 열 때 5분짜리 주소를 받고, 닫으면(이 조각이 사라지면) 버린다.
// 사진은 창 안에 그대로 보여 주고, PDF는 새 탭으로 여는 링크를 준다(주소를 받은 뒤라 팝업 차단에 걸리지 않게 누르게 한다)
export default function PosterOriginal({ opportunityId, kind, title, onClose }: PosterOriginalProps) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setState({ status: "loading" });
    getPosterUrl(opportunityId).then(
      ({ url }) => {
        if (!alive) return;
        setState({ status: "ready", url });
        if (kind === "pdf") timer = setTimeout(() => alive && setState({ status: "expired" }), LINK_MS);
      },
      (error: unknown) => {
        if (!alive) return;
        // 없어진 파일·찾을 수 없는 포스터는 다시 불러와도 같아서 다시 불러오기를 주지 않는다
        const gone = error instanceof ApiError && error.status === 404;
        setState({ status: "error", message: errorMessage(error, FAILED), retry: !gone });
      },
    );
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [opportunityId, kind, attempt]);

  // 다시 불러오기를 누르면 그 버튼이 사라지고 로딩 문구로 바뀐다 — 초점이 body로 빠지지 않게 창 내용으로 옮긴다
  const retry = () => {
    body.current?.focus();
    setAttempt((value) => value + 1);
  };

  return (
    <Modal open title="포스터 원문" onClose={onClose}>
      <div ref={body} tabIndex={-1} className="outline-none">
      {state.status === "loading" && (
        <p role="status" className="py-10 text-center text-[14px] text-[#667085]">
          포스터를 불러오는 중이에요.
        </p>
      )}
      {state.status === "error" && (
        <div className="flex flex-col items-center gap-4 py-6 text-center">
          <p role="alert" className="text-[14px] text-[#c53030]">{state.message}</p>
          {state.retry && <Button secondary onClick={retry}>다시 불러오기</Button>}
        </div>
      )}
      {state.status === "expired" && (
        <div className="flex flex-col items-center gap-4 py-6 text-center">
          <p role="status" className="text-[14px] text-[#475467]">링크를 열 수 있는 시간이 지났어요. 다시 불러와 주세요.</p>
          <Button secondary onClick={retry}>다시 불러오기</Button>
        </div>
      )}
      {state.status === "ready" && kind === "image" && (
        <img
          src={state.url}
          alt={`${title} 포스터`}
          className="mx-auto max-h-[70dvh] rounded-[14px]"
          onError={() => setState({ status: "error", message: FAILED, retry: true })}
        />
      )}
      {state.status === "ready" && kind === "pdf" && (
        <div className="flex flex-col items-center gap-4 py-6 text-center">
          <p className="text-[14px] text-[#344054]">PDF 포스터는 새 탭에서 열어요. 링크는 몇 분 동안만 열려요.</p>
          <ButtonLink href={state.url}>새 탭에서 PDF 열기</ButtonLink>
        </div>
      )}
      </div>
    </Modal>
  );
}
