import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  errorMessage,
  extractPoster,
  getPosterPreviewState,
  EXTRACT_STEPS,
  fieldErrors,
  importNoticeLink,
  NOTICE_LINK_STEPS,
  registerPosterOpportunity,
  SHOW_MOCK_NOTICE_STEPS,
  SHOW_MOCK_STEPS,
  uploadPosterFile,
} from "@/api/client";
import Header from "@/components/Header";
import NoticeLinkForm, { type LinkProblem } from "@/components/NoticeLinkForm";
import PosterAnalyzing, { type AnalyzeStep } from "@/components/PosterAnalyzing";
import PosterDropzone from "@/components/PosterDropzone";
import PosterDuplicate from "@/components/PosterDuplicate";
import PosterFileInputs from "@/components/PosterFileInputs";
import PosterExtractForm from "@/components/PosterExtractForm";
import PosterNotice from "@/components/PosterNotice";
import PosterSourcePreview from "@/components/PosterSourcePreview";
import PosterUploading from "@/components/PosterUploading";
import Skeleton from "@/components/Skeleton";
import Toast from "@/components/Toast";
import { validatePosterFile } from "@/lib/posterFile";
import useAsyncData from "@/lib/useAsyncData";
import useToast from "@/lib/useToast";
import type { PosterExtractResult } from "@/types/api";
import type { Route } from "@/types/route";

interface PosterUploadProps {
  navigate: (route: Route) => void;
}

type UploadStatus =
  | "idle"
  | "linking" // 학교 공지 링크를 읽는 중(B안)
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
const SUBTITLE = "학교 공지 링크를 붙이거나 포스터를 올리면 AI가 제목, 마감일, 지원 조건을 정리해요.";
const LINK_FAILED = "공지를 가져오지 못했어요. 잠시 후 다시 붙여 주세요";
// 화면이 기다리는 시간을 넘겼다. 실행은 계속 돌고, 끝나면 같은 주소를 다시 붙일 때 바로 열린다
const STILL_LINKING = "공지를 아직 정리하고 있어요. 잠시 뒤 같은 주소를 다시 붙이면 바로 열려요";
const REGISTER_FAILED = "공고를 등록하지 못했어요. 잠시 후 다시 시도해 주세요";

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
  const [runId, setRunId] = useState("");
  const [draft, setDraft] = useState<PosterExtractResult["draft"] | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [isPdf, setIsPdf] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [toast, showToast, , holdToast] = useToast();
  const [failureMessage, setFailureMessage] = useState(READ_FAILED);
  const [failureBadge, setFailureBadge] = useState("분석 실패");
  const linkInputRef = useRef<HTMLInputElement>(null);
  // 링크는 2분 넘게 걸릴 수 있다. 그동안 다른 화면으로 갔으면 끝나도 상세로 끌고 가지 않는다
  const onScreen = useRef(true);
  const [linkUrl, setLinkUrl] = useState("");
  const [linkProblem, setLinkProblem] = useState<LinkProblem | null>(null);

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

  useEffect(() => {
    onScreen.current = true;
    return () => {
      onScreen.current = false;
    };
  }, []);

  // 링크를 읽지 못하고 입력 칸으로 돌아오면 초점을 칸에 둔다(읽는 동안 칸이 사라져 초점을 잃었다). 고쳐서 다시 붙인다
  useEffect(() => {
    if (status === "idle" && linkProblem) linkInputRef.current?.focus();
  }, [status, linkProblem]);

  const reset = () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = null;
    setStatus("idle");
    setSteps([]);
    setResult(null);
    setRunId("");
    setProblems({});
    setDraft(null);
    setPreviewUrl("");
    setFileName("");
    setIsPdf(false);
    setFailureMessage(READ_FAILED);
    setFailureBadge("분석 실패");
  };

  // 목 모드는 실행이 없어 단계를 흉내 낸다. 실제 모드는 실행의 처리 과정을 그대로 받는다
  const runMockSteps = async (labels: string[]) => {
    for (let index = 0; index < labels.length; index += 1) {
      setSteps(
        labels.map((label, at) => ({
          label,
          status: at < index ? "succeeded" : at === index ? "running" : "pending",
        })),
      );
      await wait(600);
    }
    setSteps(labels.map((label) => ({ label, status: "succeeded" })));
  };

  // 학교 공지 링크(B안): 서버가 그 공지 한 건을 읽어 공고로 넣는다. 이미 가져온 공지면 바로 그 공고를 준다
  const importLink = async () => {
    const url = linkUrl.trim();
    if (!url) return;
    setLinkProblem(null);
    setStatus("linking");
    setSteps([{ label: NOTICE_LINK_STEPS[0], status: "running" }]);
    const reading = importNoticeLink(url, (progress) => {
      if (progress.length > 0) {
        setSteps(progress.map((step) => ({ label: step.label, status: step.status })));
      }
    })
      .then((value) => ({ value, error: null }))
      .catch((error: unknown) => ({ value: null, error }));
    if (SHOW_MOCK_NOTICE_STEPS) await runMockSteps(NOTICE_LINK_STEPS);
    const read = await reading;
    if (!onScreen.current) return; // 기다리는 동안 다른 화면으로 갔다. 가져온 공지는 피드에서 보인다
    if (read.error || !read.value) {
      // 실패 이유는 입력 칸 아래에 둔다. 주소를 고쳐 다시 붙이면 된다
      const timedOut = read.error instanceof ApiError && read.error.code === "RUN_TIMEOUT";
      setLinkProblem(
        timedOut
          ? { tone: "info", text: STILL_LINKING }
          : { tone: "error", text: fieldErrors(read.error).url ?? errorMessage(read.error, LINK_FAILED) },
      );
      setStatus("idle");
      return;
    }
    const { opportunity_id, status: found } = read.value;
    showToast(found === "new" ? "공지를 가져왔어요" : "이미 가져온 공지예요. 그 공고로 갈게요");
    setTimeout(() => {
      if (onScreen.current) navigate({ name: "opportunity", id: opportunity_id });
    }, 700);
  };

  const analyze = async (file?: File) => {
    if (!file) return;
    // 포스터로 넘어왔다. 지난 링크 문구를 지운다 — 남겨 두면 다시 올리기로 돌아올 때 초점을 링크 칸이 가져간다
    setLinkProblem(null);
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
    if (SHOW_MOCK_STEPS) await runMockSteps(EXTRACT_STEPS);

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
    const { run_id, result: read } = extracted.value;
    setRunId(run_id);
    setResult(read);
    setDraft(read.draft);
    setStatus(read.duplicate_candidate ? "duplicate" : "complete");
  };

  const register = async () => {
    if (!draft) return;
    setRegistering(true);
    setProblems({});
    try {
      const made = await registerPosterOpportunity(runId, draft);
      showToast(made.merged ? "이미 등록된 공고예요. 그 공고로 갈게요" : "공고를 등록했어요");
      setTimeout(() => navigate({ name: "opportunity", id: made.opportunity_id }), 700);
    } catch (error) {
      setRegistering(false);
      // 422는 어느 칸이 문제인지 서버가 알려 준다. 그 칸 아래에 보여 주고 안내도 띄운다
      const fields = fieldErrors(error);
      setProblems(fields);
      showToast(Object.values(fields)[0] ?? errorMessage(error, REGISTER_FAILED));
    }
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
      <Header title="공고 등록" subtitle={SUBTITLE} />
      <PosterFileInputs fileRef={fileInputRef} cameraRef={cameraInputRef} onPick={analyze} />
      {status === "idle" && (
        <>
          <NoticeLinkForm
            url={linkUrl}
            onUrlChange={setLinkUrl}
            onSubmit={importLink}
            problem={linkProblem}
            inputRef={linkInputRef}
          />
          <PosterDropzone
            onDropFile={analyze}
            onChooseFile={() => fileInputRef.current?.click()}
            onUseCamera={() => cameraInputRef.current?.click()}
          />
        </>
      )}
      {status === "linking" && <PosterAnalyzing steps={steps} title="공지를 읽고 있어요" />}
      {status === "uploading" && <PosterUploading fileName={fileName} />}
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
            problems={problems}
            onDraftChange={setDraft}
            onRegister={register}
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
      <Toast toast={toast} onHold={holdToast} />
    </>
  );
}
