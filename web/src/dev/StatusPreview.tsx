import { useState } from "react";
import {
  getDevScenario,
  scenarioLabels,
  setDevScenario,
  type DevScenario,
} from "@/dev/scenarios";

interface StatusPreviewProps {
  onChange: () => void;
}

export default function StatusPreview({ onChange }: StatusPreviewProps) {
  const [open, setOpen] = useState(false);
  const [scenario, setScenario] = useState(getDevScenario());

  const choose = (next: DevScenario) => {
    setScenario(next);
    setDevScenario(next);
    onChange();
  };

  return (
    <div className="fixed bottom-5 right-5 z-[70]">
      {open && (
        <div className="mb-3 w-[230px] rounded-[14px] border border-[#e5e7eb] bg-white p-3 shadow-[0_16px_40px_rgba(24,26,32,0.14)]">
          <p className="px-2 pb-2 text-[12px] font-semibold text-[#667085]">개발용 시나리오</p>
          {(Object.keys(scenarioLabels) as DevScenario[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => choose(item)}
              className={`block w-full rounded-[10px] px-3 py-2 text-left text-[13px] ${
                item === scenario
                  ? "bg-[#eef2ff] font-semibold text-[#4f6ef7]"
                  : "text-[#344054] hover:bg-[#f7f8fa]"
              }`}
            >
              {scenarioLabels[item]}
            </button>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white shadow-[0_8px_24px_rgba(24,26,32,0.18)]"
      >
        상태 미리보기
      </button>
    </div>
  );
}
