import { useState } from "react";
import {
  deleteAccount,
  disconnectLms,
  getDepartments,
  getLmsConnection,
  getMe,
  getProfile,
  getSettings,
  MOCK_NOW,
  reconnectCalendar,
  saveProfile,
  saveSettings,
} from "@/api/client";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Header from "@/components/Header";
import IncomeConsentSetting from "@/components/IncomeConsentSetting";
import Modal from "@/components/Modal";
import ProfileForm from "@/components/ProfileForm";
import Skeleton from "@/components/Skeleton";
import { formatRelativeTime } from "@/lib/format";
import useAsyncData from "@/lib/useAsyncData";
import type {
  LmsConnection,
  Me,
  NotificationType,
  Profile,
  Settings as SettingsData,
} from "@/types/api";
import type { Route } from "@/types/route";

interface SettingsProps {
  navigate: (route: Route) => void;
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

function SettingsSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[320px]" />
      <Skeleton className="h-48 rounded-2xl" />
      <Skeleton className="h-44 rounded-2xl" />
      <Skeleton className="h-52 rounded-2xl" />
    </>
  );
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 rounded-full ${
        checked ? "bg-[#4f6ef7]" : "bg-[#e5e7eb]"
      }`}
    >
      <span
        className={`absolute top-1 size-4 rounded-full bg-white transition ${
          checked ? "left-6" : "left-1"
        }`}
      />
    </button>
  );
}

export default function Settings({ navigate }: SettingsProps) {
  const request = useAsyncData(
    () =>
      Promise.all([
        getMe(),
        getProfile(),
        getSettings(),
        getLmsConnection(),
        getDepartments().catch(() => []),
      ]),
    [],
  );
  const [meOverride, setMeOverride] = useState<Me | null>(null);
  const [profileOverride, setProfileOverride] = useState<Profile | null>(null);
  const [settingsOverride, setSettingsOverride] =
    useState<SettingsData | null>(null);
  const [lmsOverride, setLmsOverride] = useState<LmsConnection | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteText, setDeleteText] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [toast, setToast] = useState("");

  if (request.loading) return <SettingsSkeleton />;
  if (request.error || !request.data) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "설정을 불러오지 못했어요."}
      </p>
    );
  }

  const me = meOverride ?? request.data[0];
  const profile = profileOverride ?? request.data[1];
  const settings = settingsOverride ?? request.data[2];
  const lms = lmsOverride ?? request.data[3];
  const departments = request.data[4];
  const age = profile.birth_date
    ? 2026 - Number(profile.birth_date.slice(0, 4))
    : null;
  const enrollmentLabels = {
    enrolled: "재학",
    on_leave: "휴학",
    deferred_graduation: "졸업 유예",
    graduated: "졸업",
  };
  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(""), 2400);
  };
  const updateSettings = async (next: SettingsData) => {
    setSettingsOverride(await saveSettings(next));
  };

  return (
    <>
      <Header title="설정" subtitle="프로필, 연결 서비스와 알림 설정을 관리해요." />
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-[18px] font-semibold">내 프로필</h2>
            <p className="mt-1 text-[12px] text-[#667085]">
              {me.profile_completion.filled}/{me.profile_completion.total}개 입력 완료
            </p>
          </div>
          <Button secondary onClick={() => setProfileOpen(true)}>수정</Button>
        </div>
        <div className="mt-4 grid grid-cols-5 gap-3 max-[900px]:grid-cols-2">
          {[
            ["학적", `${profile.department ?? "미입력"} · ${profile.enrollment_status ? enrollmentLabels[profile.enrollment_status] : "미입력"}`],
            ["성적", profile.gpa_last_semester ? `${profile.gpa_last_semester} / ${profile.gpa_scale}` : "미입력"],
            ["나이", age ? `${age}세` : "미입력"],
            ["지역", [profile.region_sido, profile.region_sigungu].filter(Boolean).join(" ") || "미입력"],
            ["소득", profile.income_bracket !== null ? `${profile.income_bracket}구간` : "미입력"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-[12px] bg-[#f7f8fa] p-3">
              <p className="text-[11px] text-[#667085]">{label}</p>
              <p className="mt-1 text-[13px] font-semibold">{value}</p>
            </div>
          ))}
        </div>
      </section>
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <h2 className="text-[18px] font-semibold">연결된 서비스</h2>
        <div className="mt-4 flex flex-col divide-y divide-[#e5e7eb]">
          <div className="flex items-center justify-between py-4">
            <div>
              <p className="text-[14px] font-semibold">Google Calendar</p>
              <p className="mt-1 text-[12px] text-[#667085]">
                {me.calendar_connected ? "연결됨" : "연결이 만료됐어요"}
              </p>
            </div>
            {!me.calendar_connected && (
              <Button secondary onClick={async () => setMeOverride(await reconnectCalendar())}>
                다시 연결
              </Button>
            )}
          </div>
          <div className="flex items-center justify-between py-4">
            <div>
              <p className="text-[14px] font-semibold">LearningX</p>
              <p className="mt-1 text-[12px] text-[#667085]">
                {lms.status === "active"
                  ? `토큰 끝 4자리 ${lms.token_last4} · 마지막 동기화 ${lms.last_synced_at ? formatRelativeTime(lms.last_synced_at, MOCK_NOW) : "없음"}`
                  : "연결되지 않음"}
              </p>
            </div>
            {lms.status === "active" && (
              <Button secondary onClick={() => setDisconnectOpen(true)}>연결 해제</Button>
            )}
          </div>
        </div>
      </section>
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <div className="flex items-center gap-2">
          <h2 className="text-[18px] font-semibold">알림</h2>
          <Badge tone="gray">P1</Badge>
        </div>
        <div className="mt-4 flex items-center justify-between">
          <span className="text-[14px] font-semibold">푸시 알림 켜기</span>
          <Toggle checked={settings.push_enabled} onChange={(checked) => updateSettings({ ...settings, push_enabled: checked })} />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 max-[700px]:grid-cols-1">
          {notificationOptions.map((option) => {
            const enabled = !settings.muted_notification_types.includes(option.type);
            return (
              <div key={option.type} className="flex items-center justify-between rounded-[10px] bg-[#f7f8fa] p-3">
                <span className="text-[13px]">{option.label}</span>
                <Toggle
                  checked={enabled}
                  onChange={(checked) =>
                    updateSettings({
                      ...settings,
                      muted_notification_types: checked
                        ? settings.muted_notification_types.filter((item) => item !== option.type)
                        : [...settings.muted_notification_types, option.type],
                    })
                  }
                />
              </div>
            );
          })}
        </div>
        <div className="mt-4 flex items-center justify-between">
          <span className="text-[14px] font-semibold">LMS 과제 마감을 Google Calendar에 자동으로 넣기</span>
          <Toggle checked={settings.calendar_auto_lms} onChange={(checked) => updateSettings({ ...settings, calendar_auto_lms: checked })} />
        </div>
      </section>
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <div className="flex items-center gap-2">
          <h2 className="text-[18px] font-semibold">재학생 인증</h2>
          <Badge tone="gray">P1</Badge>
        </div>
        <div className="mt-4"><Button disabled>HY-in으로 재학생 인증</Button></div>
      </section>
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <h2 className="text-[18px] font-semibold">계정</h2>
        <IncomeConsentSetting consented={me.income_info_consented} onChanged={async () => {
          setMeOverride(await getMe());
          setProfileOverride(await getProfile());
        }} />
        <button type="button" onClick={() => setDeleteOpen(true)} className="mt-4 text-[13px] font-semibold text-[#c53030]">탈퇴</button>
      </section>
      <Modal open={profileOpen} title="프로필 수정" onClose={() => setProfileOpen(false)}>
        <ProfileForm
          profile={profile}
          departments={departments}
          incomeConsented={me.income_info_consented}
          saving={savingProfile}
          onCancel={() => setProfileOpen(false)}
          onSave={async (next) => {
            setSavingProfile(true);
            setProfileOverride(await saveProfile(next));
            setMeOverride(await getMe());
            setSavingProfile(false);
            setProfileOpen(false);
            showToast("프로필을 바꿨어요. 공고를 다시 판정했어요");
          }}
        />
      </Modal>
      <Modal open={disconnectOpen} title="LearningX 연결 해제" onClose={() => setDisconnectOpen(false)}>
        <p className="text-[14px] leading-6 text-[#344054]">
          연결을 해제하면 토큰을 바로 지워요. LearningX 설정에서도 토큰을 삭제해 주세요.
        </p>
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setDisconnectOpen(false)}>취소</Button>
          <Button onClick={async () => {
            setLmsOverride(await disconnectLms());
            setDisconnectOpen(false);
          }}>연결 해제</Button>
        </div>
      </Modal>
      <Modal open={deleteOpen} title="계정 탈퇴" onClose={() => setDeleteOpen(false)}>
        <p className="text-[14px] leading-6 text-[#344054]">
          모든 개인 정보와 토큰을 지워요. 공유한 포스터 공고는 이름 없이 남아요.
        </p>
        <label className="mt-4 block text-[13px] font-semibold">
          확인을 위해 탈퇴를 입력해 주세요
          <input value={deleteText} onChange={(event) => setDeleteText(event.target.value)} className="mt-2 h-[42px] w-full rounded-[10px] border border-[#e5e7eb] px-3 outline-none focus:border-[#c53030]" />
        </label>
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setDeleteOpen(false)}>취소</Button>
          <Button disabled={deleteText !== "탈퇴"} onClick={async () => {
            await deleteAccount();
            navigate({ name: "onboarding" });
          }}>탈퇴</Button>
        </div>
      </Modal>
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          {toast}
        </div>
      )}
    </>
  );
}
