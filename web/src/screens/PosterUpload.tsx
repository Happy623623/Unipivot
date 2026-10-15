import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  errorMessage,
  extractPoster,
  getPosterPreviewState,
  EXTRACT_STEPS,
  POSTER_REGISTER_READY,
  registerPosterOpportunity,
  SHOW_MOCK_STEPS,
  uploadPosterFile,
} from "@/api/client";
import Header from "@/components/Header";
import PosterAnalyzing, { type AnalyzeStep } from "@/components/PosterAnalyzing";
import PosterDropzone from "@/components/PosterDropzone";
import PosterDuplicate from "@/components/PosterDuplicate";
import PosterFileInputs from "@/components/PosterFileInputs";
import PosterExtractForm from "@/components/PosterExtractForm";
import PosterNotice from "@/components/PosterNotice";
import PosterSourcePreview from "@/components/PosterSourcePreview";
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
  | "slow"
  | "complete"
  | "duplicate"
  | "failure"
  | "limit";

const READ_FAILED = "글자를 읽지 못했어요. 포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요";
const UPLOAD_FAILED = "파일을 올리지 못했어요. 잠시 후 다시 시도해 주세요";
// 화면이 기다리는 60초를 넘겼다. 실행은 아직 돌고 있어서 실패가 아니다
const STILL_READING = "포스터를 아직 읽고 있어요. 조금 뒤에 다시 올려 주세요";
// 등록은 아직이다. 올리기 전에 어디까지 되는지 알려 준다(끝까지 가 보고 알면 속은 느낌이 든다)
const SUBTITLE = POSTER_REGISTER_READY
  ? "포스터를 올리면 AI가 제목, 마감일, 지원 조건을 자동으로 정리해요."
  : "포스터를 올리면 AI가 제목·마감일·지원 조건을 정리해 보여 줘요. 공고로 등록하는 기능은 준비 중이에요.";

const wait = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

export default function PosterUpload({ navigate }: PosterUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const scenario = useAsyncData(getPosterPreviewState, []);
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [steps, setSteps] = useState<AnalyzeStep[]>([]);
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
    setSteps([]);
    setResult(null);
    setDraft(null);
    setPreviewUrl("");
    setFileName("");
    setIsPdf(false);
    setFailureMessage(READ_FAILED);
    setFailureBadge("분석 실패");
  };

  // 목 모드는 실행이 없어 단계를 흉내 낸다. 실제 모드는 실행의 처리 과정을 그대로 받는다
  const runMockSteps = async () => {
    for (let index = 0; index < EXTRACT_STEPS.length; index += 1) {
      setSteps(
        EXTRACT_STEPS.map((label, at) => ({
          label,
          status: at < index ? "succeeded" : at === index ? "running" : "pending",
        })),
      );
      await wait(600);
    }
    setSteps(EXTRACT_STEPS.map((label) => ({ label, status: "succeeded" })));
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
    setStatus("analyzing");
    setSteps([{ label: EXTRACT_STEPS[0], status: "running" }]);
    const extraction = extractPoster(fileId, (progress) => {
      // 실행을 막 시작했을 때는 단계 행이 아직 없다. 빈 목록으로 덮지 않는다
      if (progress.length > 0) {
        setSteps(progress.map((step) => ({ label: step.label, status: step.status })));
      }
    })
      .then((value) => ({ value, error: null }))
      .catch((error: unknown) => ({ value: null, error }));
    if (SHOW_MOCK_STEPS) await runMockSteps();

    const extracted = await extraction;
    if (extracted.error) {
      // 기다리다 끊긴 것은 실패가 아니다. 실행은 계속 돈다
      if (extracted.error instanceof ApiError && extracted.error.code === "RUN_TIMEOUT") {
        setStatus("slow");
        return;
      }
      fail(errorMessage(extracted.error, READ_FAILED), "분석 실패");
      return;
    }
    if (!extracted.value) {
      fail(READ_FAILED, "분석 실패");
      return;
    }
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
      <PosterFileInputs fileRef={fileInputRef} cameraRef={cameraInputRef} onPick={analyze} />
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
      {status === "slow" && (
        <PosterNotice
          tone="yellow"
          badge="시간이 걸려요"
          title={STILL_READING}
          action="다시 올리기"
          onAction={pickAgain}
        />
      )}
      {status === "complete" && result && draft && (
        <div className="grid grid-cols-[0.85fr_1.15fr] gap-5 max-[900px]:grid-cols-1">
          {preview}
          <PosterExtractForm
            result={result}
            draft={draft}
            registering={registering}
            registerReady={POSTER_REGISTER_READY}
            onDraftChange={setDraft}
            onRegister={register}
            onPickAgain={pickAgain}
          />
        </div>
      )}
      {status === "duplicate" && result?.duplicate_candidate && (
        <div className="grid grid-cols-[1fr_1fr] gap-5 max-[900px]:grid-cols-1">
          {preview}
          <PosterDuplicate
            title={result.duplicate_candidate.title}
            onOpen={() =>
              navigate({ name: "opportunity", id: result.duplicate_candidate!.opportunity_id })
            }
            onPickAgain={pickAgain}
          />
        </div>
      )}
      {status === "limit" && (
        <PosterNotice
          tone="red"
          badge="업로드 한도 초과"
          title="오늘은 더 올릴 수 없어요. 내일 0시부터 다시 올릴 수 있어요"
          action="홈으로"
          onAction={() => navigate({ name: "home" })}
        />
      )}
      {status === "failure" && (
        <PosterNotice
          tone="red"
          badge={failureBadge}
          title={failureMessage}
          action="다시 올리기"
          onAction={pickAgain}
        />
      )}
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          {toast}
        </div>
      )}
    </>
  );
}
