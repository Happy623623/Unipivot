import Button from "@/components/Button";

// 계획서 탭의 올리기·올리는 중·읽는 중·이미 있음 안내 (F-14). 표와 확정은 CourseSyllabus가 맡는다.
// 파일 고르기는 **버튼**으로 둔다 — 숨긴 입력을 label로 감싸면 키보드로 닿지 않는다

interface SyllabusUploadPanelProps {
  phase: "idle" | "uploading" | "reading" | "exists";
  steps: string[]; // 읽는 중일 때 보여 줄 단계 이름(실행의 처리 과정)
  portalUrl: string | null; // 과목명에서 번호를 못 뽑으면 없다(계절·비정규 과목)
  onChoose: () => void;
  onReplace: () => void;
  onCancel: () => void;
}

export default function SyllabusUploadPanel({
  phase,
  steps,
  portalUrl,
  onChoose,
  onReplace,
  onCancel,
}: SyllabusUploadPanelProps) {
  if (phase === "uploading" || phase === "reading") {
    const uploading = phase === "uploading";
    return (
      <section className="rounded-[14px] bg-[#eef2ff] p-6" aria-live="polite">
        <p className="text-[14px] font-semibold text-[#4f6ef7]">
          {uploading ? "계획서를 올리고 있어요" : "계획서를 읽고 있어요"}
        </p>
        {!uploading && (
          <ul className="mt-3 flex flex-col gap-2">
            {steps.map((label) => (
              <li key={label} className="text-[13px] text-[#344054]">
                · {label}
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  if (phase === "exists") {
    return (
      <section className="rounded-[14px] border border-[#cfd7ff] bg-white p-6">
        <p className="text-[15px] font-semibold">이 과목에는 이미 계획서가 있어요</p>
        <p className="mt-2 text-[13px] text-[#667085]">
          새 계획서로 바꾸면 지금 일정과 그 일정으로 만든 할 일·캘린더 기록이 사라져요.
        </p>
        <div className="mt-4 flex gap-2">
          <Button onClick={onReplace}>새 계획서로 바꾸기</Button>
          <button
            type="button"
            onClick={onCancel}
            className="h-[42px] rounded-[10px] border border-[#e5e7eb] px-[18px] text-[14px] font-semibold"
          >
            그만두기
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-[14px] border border-dashed border-[#e5e7eb] p-8 text-center">
      <p className="text-[16px] font-semibold">강의계획서를 직접 올려 주세요</p>
      <p className="mt-2 text-[13px] text-[#667085]">
        포털에서 강의계획서를 열고 인쇄 → PDF로 저장해 올려 주세요(글자가 있는 10쪽 이하 PDF)
      </p>
      <div className="mt-5 flex justify-center gap-2">
        {portalUrl && (
          <a
            href={portalUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-[42px] items-center rounded-[10px] border border-[#e5e7eb] px-[18px] text-[14px] font-semibold"
          >
            포털에서 강의계획서 열기
          </a>
        )}
        <Button onClick={onChoose}>PDF 올리기</Button>
      </div>
    </section>
  );
}
