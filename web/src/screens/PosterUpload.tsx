import { useEffect, useRef, useState } from "react";
import {
  extractPoster,
  getPosterPreviewState,
  MockApiError,
  registerPosterOpportunity,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Header from "@/components/Header";
import PosterExtractForm from "@/components/PosterExtractForm";
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
  | "analyzing"
  | "complete"
  | "duplicate"
  | "failure"
  | "limit";
type StepStatus = "idle" | "running" | "done";

const wait = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

function SourcePreview({
  previewUrl,
  fileName,
  isPdf,
}: {
  previewUrl: string;
  fileName: string;
  isPdf: boolean;
}) {
  return (
    <section className="flex min-h-[520px] items-center justify-center overflow-hidden rounded-[18px] border border-[#e5e7eb] bg-white p-5">
      {isPdf ? (
        <div className="text-center">
          <div className="mx-auto flex size-20 items-center justify-center rounded-[14px] bg-[#fef2f2] text-[18px] font-bold text-[#c53030]">PDF</div>
          <p className="mt-3 text-[13px] text-[#667085]">{fileName}</p>
        </div>
      ) : (
        <img src={previewUrl || "/assets/mock-opportunity-poster.svg"} alt="업로드한 포스터 미리보기" className="max-h-[640px] rounded-[14px] object-contain" />
      )}
    </section>
  );
}

export default function PosterUpload({ navigate }: PosterUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const scenario = useAsyncData(getPosterPreviewState, []);
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [steps, setSteps] = useState<[StepStatus, StepStatus, StepStatus]>([
    "idle",
    "idle",
    "idle",
  ]);
  const [result, setResult] = useState<PosterExtractResult | null>(null);
  const [draft, setDraft] = useState<PosterExtractResult["draft"] | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [isPdf, setIsPdf] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [toast, setToast] = useState("");
  const [failureMessage, setFailureMessage] = useState(
    "글자를 읽지 못했어요. 포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요",
  );

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
    setFailureMessage(
      "글자를 읽지 못했어요. 포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요",
    );
  };

  const analyze = async (file?: File) => {
    if (!file) return;
    const validationError = await validatePosterFile(file);
    if (validationError) {
      setFailureMessage(validationError);
      setStatus("failure");
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
    setStatus("analyzing");
    const extraction = extractPoster(file)
      .then((value) => ({ value, error: null }))
      .catch((error: unknown) => ({ value: null, error }));

    for (let index = 0; index < 3; index += 1) {
      setSteps((current) => current.map((step, stepIndex) => (
        stepIndex < index ? "done" : stepIndex === index ? "running" : step
      )) as [StepStatus, StepStatus, StepStatus]);
      await wait(600);
      setSteps((current) => current.map((step, stepIndex) => (
        stepIndex === index ? "done" : step
      )) as [StepStatus, StepStatus, StepStatus]);
    }

    const extracted = await extraction;
    if (extracted.error) {
      setFailureMessage(
        "글자를 읽지 못했어요. 포스터 전체가 보이게 밝은 곳에서 다시 찍어 주세요",
      );
      setStatus(
        extracted.error instanceof MockApiError && extracted.error.code === "upload_limit"
          ? "limit"
          : "failure",
      );
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

  if (scenario.loading) {
    return (
      <>
        <Skeleton className="h-[70px] w-[430px]" />
        <Skeleton className="h-[310px] w-full rounded-[18px]" />
      </>
    );
  }

  const uploadInputs = (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".jpg,.jpeg,.png,.webp,.heic,.pdf"
        className="hidden"
        onChange={(event) => analyze(event.target.files?.[0])}
      />
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(event) => analyze(event.target.files?.[0])}
      />
    </>
  );

  return (
    <>
      <Header title="포스터로 공고 등록" subtitle="포스터를 올리면 AI가 제목, 마감일, 지원 조건을 자동으로 정리해요." />
      {uploadInputs}
      {status === "idle" && (
        <section
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            analyze(event.dataTransfer.files[0]);
          }}
          className="flex h-[310px] flex-col items-center justify-center gap-3 rounded-[18px] border border-dashed border-[#e5e7eb] bg-white"
        >
          <span className="text-[34px] font-bold text-[#4f6ef7]">↑</span>
          <p className="text-[18px] font-semibold">이미지 또는 PDF를 업로드해주세요</p>
          <p className="text-[13px] text-[#667085]">JPG · PNG · WEBP · HEIC 또는 2쪽 이하 PDF · 20MB 이하</p>
          <div className="flex gap-2">
            <Button onClick={() => fileInputRef.current?.click()}>파일 선택</Button>
            <span className="hidden max-[760px]:inline-flex">
              <Button secondary onClick={() => cameraInputRef.current?.click()}>사진 찍기</Button>
            </span>
          </div>
        </section>
      )}
      {status === "analyzing" && (
        <div className="grid grid-cols-[1fr_1fr] gap-5 max-[900px]:grid-cols-1">
          <SourcePreview previewUrl={previewUrl} fileName={fileName} isPdf={isPdf} />
          <section className="rounded-[18px] border border-[#e5e7eb] bg-white p-6">
            <h2 className="text-[20px] font-bold">포스터를 분석하고 있어요</h2>
            <div className="mt-5 flex flex-col gap-3">
              {["포스터에서 글자·날짜 읽기", "지원 자격 정리", "내 프로필과 비교"].map((label, index) => (
                <div key={label} className="flex items-center justify-between rounded-[12px] bg-[#f7f8fa] p-4 text-[14px]">
                  <span>{label}</span>
                  <Badge tone={steps[index] === "done" ? "green" : "blue"}>
                    {steps[index] === "done" ? "완료" : steps[index] === "running" ? "진행 중" : "대기"}
                  </Badge>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
      {status === "complete" && result && draft && (
        <div className="grid grid-cols-[0.85fr_1.15fr] gap-5 max-[900px]:grid-cols-1">
          <SourcePreview previewUrl={previewUrl} fileName={fileName} isPdf={isPdf} />
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
          <SourcePreview previewUrl={previewUrl} fileName={fileName} isPdf={isPdf} />
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
          <Badge tone="red">{status === "limit" ? "업로드 한도 초과" : "분석 실패"}</Badge>
          <h2 className="mt-4 text-[20px] font-bold">
            {status === "limit"
              ? "오늘은 더 올릴 수 없어요. 내일 0시부터 다시 올릴 수 있어요"
              : failureMessage}
          </h2>
          {status === "failure" && (
            <div className="mt-5">
              <Button onClick={() => {
                reset();
                setTimeout(() => fileInputRef.current?.click());
              }}>
                다시 올리기
              </Button>
            </div>
          )}
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
