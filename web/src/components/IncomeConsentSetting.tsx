import { useState } from "react";
import { updateIncomeConsent } from "@/api/client";
import Button from "@/components/Button";
import Modal from "@/components/Modal";

interface IncomeConsentSettingProps {
  consented: boolean; // GET /me의 income_info_consented
  onChanged: () => Promise<void>; // 내 정보·프로필 다시 불러오기
}

// 설정 화면: 소득·수급 정보 선택 동의 켜기·끄기 (PATCH /me/consents)
export default function IncomeConsentSetting({ consented, onChanged }: IncomeConsentSettingProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const change = async (agree: boolean) => {
    setSaving(true);
    try {
      await updateIncomeConsent(agree);
      await onChanged();
    } finally {
      setSaving(false);
      setConfirmOpen(false);
    }
  };

  return (
    <>
      <div className="mt-4 flex items-center justify-between gap-4">
        <div>
          <p className="text-[14px] font-semibold">소득·수급 정보 수집·이용 (선택)</p>
          <p className="mt-1 text-[12px] text-[#667085]">자격 판정에만 쓰고, 탈퇴하면 바로 지워요.</p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={consented}
          aria-label="소득·수급 정보 수집·이용 동의"
          disabled={saving}
          onClick={() => (consented ? setConfirmOpen(true) : change(true))}
          className={`relative h-6 w-11 shrink-0 rounded-full ${consented ? "bg-[#4f6ef7]" : "bg-[#e5e7eb]"}`}
        >
          <span className={`absolute top-1 size-4 rounded-full bg-white transition ${consented ? "left-6" : "left-1"}`} />
        </button>
      </div>
      <Modal open={confirmOpen} title="소득·수급 정보 동의 철회" onClose={() => setConfirmOpen(false)}>
        <p className="text-[14px] leading-6 text-[#344054]">
          입력한 소득·수급 정보가 바로 지워져요. 소득 조건이 있는 공고는 다시 판정해요.
        </p>
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setConfirmOpen(false)}>취소</Button>
          <Button disabled={saving} onClick={() => change(false)}>동의 철회</Button>
        </div>
      </Modal>
    </>
  );
}
