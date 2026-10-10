import { useState } from "react";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import type { ReportReason } from "@/types/api";

interface ReportModalProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (reason: ReportReason, detail: string) => void;
}

const reasons: { value: ReportReason; label: string }[] = [
  { value: "wrong_info", label: "잘못된 정보" },
  { value: "duplicate", label: "중복" },
  { value: "expired", label: "마감됨" },
  { value: "inappropriate", label: "부적절" },
];

export default function ReportModal({ open, onClose, onSubmit }: ReportModalProps) {
  const [reason, setReason] = useState<ReportReason>("wrong_info");
  const [detail, setDetail] = useState("");

  return (
    <Modal open={open} title="공고 신고" onClose={onClose}>
      <div className="grid grid-cols-2 gap-2">
        {reasons.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => setReason(item.value)}
            className={`rounded-[10px] border px-3 py-3 text-[13px] font-semibold ${
              reason === item.value
                ? "border-[#4f6ef7] bg-[#eef2ff] text-[#4f6ef7]"
                : "border-[#e5e7eb] text-[#667085]"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
      <label className="mt-4 block">
        <span className="mb-2 block text-[13px] font-semibold">상세 내용</span>
        <textarea
          value={detail}
          onChange={(event) => setDetail(event.target.value)}
          className="min-h-28 w-full resize-none rounded-[10px] border border-[#e5e7eb] p-3 text-[14px] outline-none focus:border-[#4f6ef7]"
          placeholder="확인이 필요한 내용을 적어 주세요."
        />
      </label>
      <div className="mt-6 flex justify-end gap-2">
        <Button secondary onClick={onClose}>취소</Button>
        <Button onClick={() => onSubmit(reason, detail.trim())}>신고하기</Button>
      </div>
    </Modal>
  );
}
