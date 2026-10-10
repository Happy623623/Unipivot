import { useState } from "react";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import type { Condition } from "@/types/api";

interface ProfileInputModalProps {
  open: boolean;
  missingFields: string[];
  conditions: Condition[];
  saving: boolean;
  onClose: () => void;
  onSave: (values: Record<string, string>) => void;
}

const sensitiveFields = ["income_bracket", "median_income_pct", "welfare_status"];

export default function ProfileInputModal({
  open,
  missingFields,
  conditions,
  saving,
  onClose,
  onSave,
}: ProfileInputModalProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const hasSensitiveField = missingFields.some((field) => sensitiveFields.includes(field));

  return (
    <Modal open={open} title="정보 입력" onClose={onClose}>
      {hasSensitiveField && (
        <p className="mb-4 rounded-[10px] bg-[#fff8e1] p-3 text-[12px] text-[#b7791f]">
          자격 판정에만 쓰고, 탈퇴하면 바로 지워요
        </p>
      )}
      <div className="flex flex-col gap-4">
        {missingFields.map((field) => {
          const condition = conditions.find((item) => item.field === field);
          return (
            <label key={field}>
              <span className="mb-2 block text-[13px] font-semibold">{condition?.label ?? field}</span>
              <input
                value={values[field] ?? ""}
                onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
                className="h-[42px] w-full rounded-[10px] border border-[#e5e7eb] px-3 text-[14px] outline-none focus:border-[#4f6ef7]"
                placeholder={`${condition?.label ?? field} 입력`}
              />
            </label>
          );
        })}
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button secondary onClick={onClose}>취소</Button>
        <Button onClick={() => onSave(values)} disabled={saving}>
          {saving ? "다시 판정 중" : "저장하고 다시 판정"}
        </Button>
      </div>
    </Modal>
  );
}
