interface ToggleProps {
  checked: boolean;
  label: string; // 화면에 글이 따로 있어 스위치에는 읽기용 이름만 준다
  disabled?: boolean; // 지금은 켤 수 없음(브라우저가 알림을 막았다 등). 초점을 받지 않는다
  busy?: boolean; // 바꾸는 중. 초점은 남기고 누름은 무시한다(Button의 busy와 같다). disabled와 같이 주지 않는다
  onChange: (checked: boolean) => void;
}

// 설정의 켜기·끄기 스위치. 알림 설정과 브라우저 알림 줄이 함께 쓴다
export default function Toggle({ checked, label, disabled = false, busy = false, onChange }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      aria-disabled={busy || undefined}
      aria-busy={busy || undefined}
      onClick={() => {
        if (!busy) onChange(!checked);
      }}
      className={`relative h-6 w-11 shrink-0 rounded-full disabled:cursor-not-allowed disabled:opacity-45 aria-disabled:cursor-wait aria-disabled:opacity-45 ${checked ? "bg-[#4f6ef7]" : "bg-[#e5e7eb]"}`}
    >
      <span className={`absolute top-1 size-4 rounded-full bg-white transition ${checked ? "left-6" : "left-1"}`} />
    </button>
  );
}
