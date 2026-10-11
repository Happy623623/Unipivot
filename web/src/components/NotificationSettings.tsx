import Badge from "@/components/Badge";
import type { NotificationType, Settings } from "@/types/api";

interface NotificationSettingsProps {
  settings: Settings; // GET /me/settings (P1)
  onChange: (next: Settings) => void;
}

const notificationOptions: { type: NotificationType; label: string }[] = [
  { type: "new_eligible", label: "새 지원 가능 공고" },
  { type: "deadline_soon", label: "공고 마감 임박" },
  { type: "new_assignment", label: "새 LMS 과제" },
  { type: "new_material", label: "새 강의자료" },
  { type: "task_due", label: "할 일 마감" },
  { type: "schedule_change", label: "수업 일정 변경" },
  { type: "profile_needed", label: "프로필 정보 필요" },
];

function Toggle({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 shrink-0 rounded-full ${checked ? "bg-[#4f6ef7]" : "bg-[#e5e7eb]"}`}
    >
      <span className={`absolute top-1 size-4 rounded-full bg-white transition ${checked ? "left-6" : "left-1"}`} />
    </button>
  );
}

// 설정의 알림 구역 (P1, F-06): 푸시 켜기, 종류별 끄기, LMS 과제 자동 캘린더 등록
export default function NotificationSettings({ settings, onChange }: NotificationSettingsProps) {
  return (
    <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
      <div className="flex items-center gap-2">
        <h2 className="text-[18px] font-semibold">알림</h2>
        <Badge tone="gray">P1</Badge>
      </div>
      <div className="mt-4 flex items-center justify-between gap-4">
        <span className="text-[14px] font-semibold">푸시 알림 켜기</span>
        <Toggle
          checked={settings.push_enabled}
          label="푸시 알림 켜기"
          onChange={(checked) => onChange({ ...settings, push_enabled: checked })}
        />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 max-[700px]:grid-cols-1">
        {notificationOptions.map((option) => (
          <div key={option.type} className="flex items-center justify-between gap-3 rounded-[10px] bg-[#f7f8fa] p-3">
            <span className="text-[13px]">{option.label}</span>
            <Toggle
              checked={!settings.muted_notification_types.includes(option.type)}
              label={option.label}
              onChange={(checked) =>
                onChange({
                  ...settings,
                  muted_notification_types: checked
                    ? settings.muted_notification_types.filter((item) => item !== option.type)
                    : [...settings.muted_notification_types, option.type],
                })
              }
            />
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-center justify-between gap-4">
        <span className="text-[14px] font-semibold">LMS 과제 마감을 Google Calendar에 자동으로 넣기</span>
        <Toggle
          checked={settings.calendar_auto_lms}
          label="LMS 과제 마감을 Google Calendar에 자동으로 넣기"
          onChange={(checked) => onChange({ ...settings, calendar_auto_lms: checked })}
        />
      </div>
    </section>
  );
}
