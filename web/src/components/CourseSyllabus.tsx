import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  confirmSyllabus,
  errorMessage,
  extractSyllabus,
  fieldErrors,
  registerSyllabusCalendarEvent,
  SYLLABUS_STEPS,
  uploadSyllabusFile,
} from "@/api/client";
import SyllabusConfirmedList from "@/components/SyllabusConfirmedList";
import SyllabusFileInput from "@/components/SyllabusFileInput";
import SyllabusReviewPanel from "@/components/SyllabusReviewPanel";
import { toReviewRows, type ReviewRow } from "@/components/SyllabusReviewTable";
import SyllabusUploadPanel from "@/components/SyllabusUploadPanel";
import { toKstIso } from "@/lib/format";
import type { CourseDetail, ProcessStep, SyllabusItemView } from "@/types/api";

// 과목 상세의 "계획서" 탭 (F-14). 포털 계획서를 PDF로 올리면 시험·발표 일정을 뽑아 주고,
// 학생이 확인한 것만 플래너·캘린더로 보낸다. 캘린더 체크는 연결한 학생에게만 보여 준다

interface CourseSyllabusProps {
  course: CourseDetail;
  calendarConnected: boolean;
  calendarResult: "connected" | "error" | null; // Google 연결에서 돌아온 결과
  onRefresh: () => void; // 과목 상세를 다시 받는다(확정 표시·뽑아 둔 일정)
  onConnectCalendar: () => Promise<void>; // 실제 모드는 페이지를 떠난다
  onToast: (text: string) => void;
}

type Phase = "idle" | "uploading" | "reading" | "review" | "saving" | "exists";

const UPLOAD_FAILED = "계획서를 올리지 못했어요. 잠시 후 다시 시도해 주세요.";
const READ_FAILED = "계획서에서 일정을 읽지 못했어요. 포털 계획서를 PDF로 저장해 올려 주세요.";
const STILL_READING = "계획서를 아직 읽고 있어요. 조금 뒤에 계획서 탭을 다시 열어 주세요.";
const CONFIRM_FAILED = "일정을 저장하지 못했어요. 잠시 후 다시 시도해 주세요.";
const CALENDAR_FAILED = "캘린더에 넣지 못했어요. 잠시 후 다시 시도해 주세요.";
const NO_DATE = "날짜와 시각을 적어 주세요. 비어 있는 일정은 넣을 수 없어요.";
const MAX_BYTES = 20 * 1024 * 1024; // 서버와 같은 한도(명세 6장)

export default function CourseSyllabus({
  course,
  calendarConnected,
  calendarResult,
  onRefresh,
  onConnectCalendar,
  onToast,
}: CourseSyllabusProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const alive = useRef(true);
  const [phase, setPhase] = useState<Phase>("idle");
  const [steps, setSteps] = useState<string[]>(SYLLABUS_STEPS);
  const [rows, setRows] = useState<ReviewRow[]>([]);
  const [syllabusId, setSyllabusId] = useState("");
  const [connected, setConnected] = useState(calendarConnected);
  const [withCalendar, setWithCalendar] = useState(calendarConnected);
  const [problem, setProblem] = useState("");
  const [problems, setProblems] = useState<Record<string, string>>({}); // 422 항목 오류
  const [pending, setPending] = useState<File | null>(null); // "바꾸기"를 기다리는 파일
  const [added, setAdded] = useState<string[]>([]);
  const [busyItem, setBusyItem] = useState<string | null>(null);
  // 끝난 요청이 사라진 화면에 값을 쓰지 않게 하는 표시. **다시 붙을 때 되살려야** 한다 —
  // React StrictMode는 효과를 붙였다 떼었다 다시 붙이므로, 되살리지 않으면 첫 화면이 영영 멈춘다
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    setConnected(calendarConnected);
    setWithCalendar(calendarConnected);
  }, [calendarConnected]);
  useEffect(() => {
    if (calendarResult === "error") setProblem("Google 캘린더를 연결하지 못했어요. 다시 눌러 주세요.");
  }, [calendarResult]);

  const confirmedItems = course.syllabus_items.filter((item) => item.is_confirmed);
  const waiting = course.syllabus_items.length - confirmedItems.length;

  const connect = async () => {
    setProblem("");
    try {
      await onConnectCalendar(); // 실제 모드는 여기서 페이지를 떠난다
      if (!alive.current) return;
      setConnected(true);
      setWithCalendar(true);
    } catch (error) {
      setProblem(errorMessage(error, "Google 캘린더 연결을 시작하지 못했어요."));
    }
  };

  const read = async (file: File, replace: boolean) => {
    setProblem("");
    setProblems({});
    setPhase("uploading");
    setSteps(SYLLABUS_STEPS);
    try {
      const uploaded = await uploadSyllabusFile(file);
      if (!alive.current) return;
      setPhase("reading");
      const extraction = await extractSyllabus(uploaded.file_id, course.course.id, {
        replace,
        onSteps: (value: ProcessStep[]) => alive.current && setSteps(value.map((one) => one.label)),
      });
      if (!alive.current) return;
      setSyllabusId(extraction.result.syllabus_id);
      setRows(toReviewRows(extraction.result.items));
      setPhase("review");
      if (extraction.result.items.length === 0) {
        setProblem("계획서에서 시험·발표 일정을 찾지 못했어요. 플래너에 직접 적어 주세요.");
      }
    } catch (error) {
      if (!alive.current) return;
      if (error instanceof ApiError && error.code === "SYLLABUS_EXISTS") {
        setPending(file); // 갈아 끼울지 물어본다
        setPhase("exists");
        return;
      }
      // 60초를 넘겨도 실행은 돌고 있다. 올리기와 읽기는 고칠 방법이 달라 문구도 다르다
      const unfinished = error instanceof ApiError && error.code === "RUN_TIMEOUT";
      const failed = error instanceof ApiError && error.status === 422;
      setProblem(
        unfinished ? STILL_READING : errorMessage(error, failed ? READ_FAILED : UPLOAD_FAILED),
      );
      setPhase("idle");
    }
  };

  const pick = (file?: File) => {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setProblem("파일이 20MB를 넘어요. 더 작은 파일로 올려 주세요.");
      return;
    }
    void read(file, phase === "exists");
  };

  // 다시 올리지 않고 확인 화면을 연다(뽑아 두고 확인하지 않은 일정, 명세 9장의 syllabus_id)
  const review = () => {
    if (!course.course.syllabus_id) return;
    setProblem("");
    setProblems({});
    setSyllabusId(course.course.syllabus_id);
    setRows(toReviewRows(course.syllabus_items));
    setPhase("review");
  };

  // 확인 화면에서 나간다. 뽑은 일정은 서버에 남아 있어서, 상세를 다시 받으면
  // "확인하지 않은 일정 N건"으로 보이고 다시 올리지 않고 이어서 확인할 수 있다
  const cancel = () => {
    setPhase("idle");
    onRefresh();
  };

  const save = async () => {
    const chosen = rows.filter((row) => row.selected);
    if (chosen.some((row) => !row.date || !row.time)) {
      setProblem(NO_DATE);
      return;
    }
    setProblem("");
    setProblems({});
    setPhase("saving");
    try {
      const result = await confirmSyllabus(
        syllabusId,
        rows.map((row) => ({
          id: row.id,
          title: row.title.trim(),
          starts_at: row.date ? toKstIso(row.date, row.time) : null,
          selected: row.selected,
        })),
        withCalendar,
      );
      if (!alive.current) return;
      onToast(summary(result.planner_tasks_created, result.calendar_events_created, withCalendar));
      setPhase("idle");
      onRefresh();
    } catch (error) {
      if (!alive.current) return;
      if (error instanceof ApiError && error.code === "CALENDAR_NOT_CONNECTED") {
        setProblem("Google 캘린더 연결이 풀렸어요. 아래에서 다시 연결한 뒤 눌러 주세요.");
        setConnected(false);
        setWithCalendar(false);
        setPhase("review");
        return;
      }
      setProblems(fieldErrors(error));
      setProblem(errorMessage(error, CONFIRM_FAILED));
      setPhase("review");
    }
  };

  const addToCalendar = async (item: SyllabusItemView) => {
    setProblem("");
    setBusyItem(item.id);
    try {
      await registerSyllabusCalendarEvent(item.id);
      if (!alive.current) return;
      setAdded((current) => (current.includes(item.id) ? current : [...current, item.id]));
      onToast("캘린더에 넣었어요");
    } catch (error) {
      if (!alive.current) return;
      if (error instanceof ApiError && error.code === "CALENDAR_NOT_CONNECTED") {
        setConnected(false); // 권한이 풀렸다. 다시 연결하는 버튼으로 바뀐다
        setProblem("Google 캘린더 연결이 풀렸어요. 다시 연결해 주세요.");
        return;
      }
      setProblem(errorMessage(error, CALENDAR_FAILED));
    } finally {
      if (alive.current) setBusyItem(null);
    }
  };

  const notice = (
    <p
      role="status"
      className={
        problem
          ? "mb-4 rounded-[10px] bg-[#fef2f2] px-4 py-3 text-[13px] text-[#c53030]"
          : "sr-only"
      }
    >
      {problem}
    </p>
  );
  const input = <SyllabusFileInput inputRef={fileRef} onPick={pick} />;
  const choose = () => fileRef.current?.click();

  if (phase === "review" || phase === "saving") {
    return (
      <>
        {input}
        {notice}
        <SyllabusReviewPanel
          rows={rows}
          problems={problems}
          saving={phase === "saving"}
          connected={connected}
          withCalendar={withCalendar}
          onRows={setRows}
          onWithCalendar={setWithCalendar}
          onConnect={() => void connect()}
          onCancel={cancel}
          onSave={() => void save()}
        />
      </>
    );
  }

  if (phase === "idle" && course.course.has_syllabus) {
    return (
      <>
        {input}
        {notice}
        <SyllabusConfirmedList
          items={confirmedItems}
          waiting={waiting}
          canReview={course.course.syllabus_id !== null}
          calendarConnected={connected}
          added={added}
          busyItem={busyItem}
          onAddToCalendar={(item) => void addToCalendar(item)}
          onConnectCalendar={() => void connect()}
          onReview={review}
          onUpload={choose}
        />
      </>
    );
  }

  return (
    <>
      {input}
      {notice}
      <SyllabusUploadPanel
        phase={phase}
        steps={steps}
        portalUrl={course.course.portal_syllabus_url}
        onChoose={choose}
        onReplace={() => pending && void read(pending, true)}
        onCancel={() => {
          setPending(null);
          cancel();
        }}
      />
    </>
  );
}

// 확정 결과 안내. **새로 만든** 할 일 수를 센다(이미 있던 할 일은 날짜만 맞춘다, 명세 8장)
function summary(tasks: number, events: number, withCalendar: boolean): string {
  const planner = tasks > 0 ? `할 일 ${tasks}건을 플래너에 넣었어요` : "플래너는 그대로예요";
  if (!withCalendar) return planner;
  return events > 0
    ? `${planner} · 캘린더 ${events}건`
    : `${planner} · 캘린더에 새로 넣을 일정은 없었어요`;
}
