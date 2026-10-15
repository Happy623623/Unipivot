import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  errorMessage,
  extractPoster,
  getPosterPreviewState,
  POSTER_EXTRACT_READY,
  registerPosterOpportunity,
  uploadPosterFile,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Header from "@/components/Header";
import PosterAnalyzing, { type StepStatus } from "@/components/PosterAnalyzing";
import PosterDropzone from "@/components/PosterDropzone";
import PosterExtractForm from "@/components/PosterExtractForm";
import PosterSourcePreview from "@/components/PosterSourcePreview";
import PosterStored from "@/components/PosterStored";
import Skeleton from "@/components/Skeleton";
import { validatePosterFile } from "@/lib/posterFile";
import useAsyncData from "@/lib/useAsyncData";
import type { PosterExtractResult } from "@/types/api";
import type { Route } from "@/types/route";

interface PosterUploadProps {
  navigate: (route: Route) => void;
}

type UploadStatus =
  | "idle"
  | "uploading"
  | "analyzing"
  | "stored"
  | "complete"
  | "duplicate"
  | "failure"
  | "limit";

const READ_FAILED = "글자를 읽지 못했어요. 포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요";
const UPLOAD_FAILED = "파일을 올리지 못했어요. 잠시 후 다시 시도해 주세요";
// 실제 모드는 아직 올려 두기만 한다. 올리기 전에 미리 알려 준다(올린 뒤에 말하면 속은 느낌이 든다)
const SUBTITLE = POSTER_EXTRACT_READY
  ? "포스터를 올리면 AI가 제목, 마감일, 지원 조건을 자동으로 정리해요."
  : "지금은 포스터를 올려 두기만 해요. 제목·마감일을 자동으로 정리하는 기능은 준비 중이에요.";

const wait = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

export default function PosterUpload({ navigate }: PosterUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const scenario = useAsyncData(getPosterPreviewState, []);
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [steps, setSteps] = useState<StepStatus[]>(["idle", "idle", "idle"]);
  const [result, setResult] = useState<PosterExtractResult | null>(null);
  const [draft, setDraft] = useState<PosterExtractResult["draft"] | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [isPdf, setIsPdf] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [toast, setToast] = useState("");
  const [failureMessage, setFailureMessage] = useState(READ_FAILED);
  const [failureBadge, setFailureBadge] = useState("분석 실패");

  const fail = (message: string, badge: string) => {
    setFailureMessage(message);
    setFailureBadge(badge);
    setStatus("failure");
  };

  useEffect(() => {
    if (!scenario.data) return;
    if (scenario.data.status === "duplicate") {
      setStatus("duplicate");
      setResult(scenario.data.result);
      setDraft(scenario.data.result.draft);
      setPreviewUrl("/assets/mock-opportunity-poster.svg");
    } else {
      setStatus(scenario.data.status);
    }
  }, [scenario.data]);

  useEffect(
    () => () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    },
    [],
  );

  const reset = () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = null;
    setStatus("idle");
    setSteps(["idle", "idle", "idle"]);
    setResult(null);
    setDraft(null);
    setPreviewUrl("");
    setFileName("");
    setIsPdf(false);
    setFailureMessage(READ_FAILED);
    setFailureBadge("분석 실패");
  };

  const runSteps = async () => {
    for (let index = 0; index < 3; index += 1) {
      setSteps((current) => current.map((step, at) => (
        at < index ? "done" : at === index ? "running" : step
      )));
      await wait(600);
      setSteps((current) => current.map((step, at) => (at === index ? "done" : step)));
    }
  };

  const analyze = async (file?: File) => {
    if (!file) return;
    const validationError = await validatePosterFile(file);
    if (validationError) {
      fail(validationError, "올릴 수 없는 파일");
      return;
    }

    const pdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
    setIsPdf(pdf);
    setFileName(file.name);
    if (!pdf) {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = URL.createObjectURL(file);
      setPreviewUrl(objectUrlRef.current);
    }

    setStatus("uploading");
    let fileId: string;
    try {
      fileId = (await uploadPosterFile(file)).file_id;
    } catch (error) {
      if (error instanceof ApiError && error.code === "DAILY_UPLOAD_LIMIT") {
        setStatus("limit");
        return;
      }
      fail(errorMessage(error, UPLOAD_FAILED), "올리지 못했어요");
      return;
    }
    if (!POSTER_EXTRACT_READY) {
      setStatus("stored");
      return;
    }

    setStatus("analyzing");
    const extraction = extractPoster(fileId)
      .then((value) => ({ value, error: null }))
      .catch((error: unknown) => ({ value: null, error }));
    await runSteps();

    const extracted = await extraction;
    if (extracted.error) {
      fail(READ_FAILED, "분석 실패");
      return;
    }
    if (!extracted.value) return;
    setResult(extracted.value);
    setDraft(extracted.value.draft);
    setStatus(extracted.value.duplicate_candidate ? "duplicate" : "complete");
  };

  const register = async () => {
    if (!draft) return;
    setRegistering(true);
    const detail = await registerPosterOpportunity(draft);
    setToast("공고를 등록했어요");
    setTimeout(() => navigate({ name: "opportunity", id: detail.id }), 700);
  };

  const pickAgain = () => {
    reset();
    setTimeout(() => fileInputRef.current?.click());
  };

  if (scenario.loading) {
    return (
      <>
        <Skeleton className="h-[70px] w-[430px]" />
        <Skeleton className="h-[310px] w-full rounded-[18px]" />
      </>
    );
  }

  const preview = (
    <PosterSourcePreview previewUrl={previewUrl} fileName={fileName} isPdf={isPdf} />
  );

  return (
    <>
      <Header title="포스터로 공고 등록" subtitle={SUBTITLE} />
      <input
        ref={fileInputRef}
        type="file"
        accept=".jpg,.jpeg,.png,.webp,.pdf"
        className="hidden"
        onChange={(event) => {
          const picked = event.target.files?.[0];
          event.target.value = "";  // 같은 파일을 다시 골라도 change가 뜨게 비운다
          analyze(picked);
        }}
      />
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        capture="environment"
        className="hidden"
        onChange={(event) => {
          const picked = event.target.files?.[0];
          event.target.value = "";
          analyze(picked);
        }}
      />
      {status === "idle" && (
        <PosterDropzone
          onDropFile={analyze}
          onChooseFile={() => fileInputRef.current?.click()}
          onUseCamera={() => cameraInputRef.current?.click()}
        />
      )}
      {status === "uploading" && (
        <section className="flex min-h-[310px] flex-col items-center justify-center gap-3 rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center" role="status">
          <p className="text-[18px] font-semibold">포스터를 올리고 있어요</p>
          <p className="text-[13px] text-[#667085]">{fileName}</p>
        </section>
      )}
      {status === "analyzing" && (
        <div className="grid grid-cols-[1fr_1fr] gap-5 max-[900px]:grid-cols-1">
          {preview}
          <PosterAnalyzing steps={steps} />
        </div>
      )}
      {status === "stored" && (
        <div className="grid grid-cols-[1fr_1fr] gap-5 max-[900px]:grid-cols-1">
          {preview}
          <PosterStored onHome={() => navigate({ name: "home" })} onPickAgain={pickAgain} />
        </div>
      )}
      {status === "complete" && result && draft && (
        <div className="grid grid-cols-[0.85fr_1.15fr] gap-5 max-[900px]:grid-cols-1">
          {preview}
          <PosterExtractForm
            result={result}
            draft={draft}
            registering={registering}
            onDraftChange={setDraft}
            onRegister={register}
          />
        </div>
      )}
      {status === "duplicate" && result?.duplicate_candidate && (
        <div className="grid grid-cols-[1fr_1fr] gap-5 max-[900px]:grid-cols-1">
          {preview}
          <section className="flex min-h-[300px] flex-col items-center justify-center rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center">
            <Badge tone="yellow">중복 공고</Badge>
            <h2 className="mt-4 text-[22px] font-bold">이미 등록된 공고예요</h2>
            <p className="mt-2 text-[14px] text-[#667085]">{result.duplicate_candidate.title}</p>
            <div className="mt-5">
              <Button onClick={() => navigate({ name: "opportunity", id: result.duplicate_candidate!.opportunity_id })}>
                기존 공고 보기
              </Button>
            </div>
          </section>
        </div>
      )}
      {(status === "failure" || status === "limit") && (
        <section className="flex min-h-[310px] flex-col items-center justify-center rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center">
          <Badge tone="red">{status === "limit" ? "업로드 한도 초과" : failureBadge}</Badge>
          <h2 className="mt-4 text-[20px] font-bold">
            {status === "limit"
              ? "오늘은 더 올릴 수 없어요. 내일 0시부터 다시 올릴 수 있어요"
              : failureMessage}
          </h2>
          <div className="mt-5">
            {status === "failure" ? (
              <Button onClick={pickAgain}>다시 올리기</Button>
            ) : (
              <Button onClick={() => navigate({ name: "home" })}>홈으로</Button>
            )}
          </div>
        </section>
      )}
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          {toast}
        </div>
      )}
    </>
  );
}
