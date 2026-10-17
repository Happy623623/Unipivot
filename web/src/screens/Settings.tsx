import { useState } from "react";
import {
  consentRequired,
  DELETE_ACCOUNT_READY,
  deleteAccount,
  errorMessage,
  fieldErrors,
  getDepartments,
  getLmsConnection,
  getMe,
  getProfile,
  getSettings,
  saveProfile,
  saveSettings,
} from "@/api/client";
import Button from "@/components/Button";
import ConnectedServices, { type CalendarResult } from "@/components/ConnectedServices";
import Header from "@/components/Header";
import IncomeConsentSetting from "@/components/IncomeConsentSetting";
import Modal from "@/components/Modal";
import NotificationSettings from "@/components/NotificationSettings";
import ProfileForm from "@/components/ProfileForm";
import Skeleton from "@/components/Skeleton";
import { DEGREE_LABELS, regionText, type ProfileErrors } from "@/lib/profileFields";
import useAsyncData from "@/lib/useAsyncData";
import type { Me, Profile, Settings as SettingsData } from "@/types/api";
import type { Route } from "@/types/route";

interface SettingsProps {
  navigate: (route: Route) => void;
  calendarResult?: CalendarResult | null; // 캘린더 연결에서 돌아온 결과 (/settings?calendar=…)
}

const PROFILE_FAILED = "프로필을 저장하지 못했어요. 입력한 값은 그대로 있으니 다시 눌러 주세요.";

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

export default function Settings({ navigate, calendarResult = null }: SettingsProps) {
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
  const [profileOpen, setProfileOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteText, setDeleteText] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState<{ message: string; fields: ProfileErrors } | null>(null);
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
  const academicStatus = [
    profile.degree_program ? DEGREE_LABELS[profile.degree_program] : null,
    profile.enrollment_status ? enrollmentLabels[profile.enrollment_status] : null,
  ].filter(Boolean).join(" ");
  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(""), 2400);
  };
  // 토글은 누르는 즉시 움직이고(낙관), 저장에 실패하면 되돌리고 알려 준다. 서버 응답으로
  // 다시 덮어쓰지 않는다 — 연달아 누르면 늦게 온 응답이 마지막 클릭을 덮어쓴다
  const updateSettings = async (next: SettingsData) => {
    const before = settings;
    setSettingsOverride(next);
    try {
      await saveSettings(next);
    } catch (caught) {
      setSettingsOverride(before);
      showToast(errorMessage(caught, "설정을 저장하지 못했어요. 잠시 후 다시 눌러 주세요."));
    }
  };
  const openProfile = (open: boolean) => {
    setProfileError(null);
    setProfileOpen(open);
  };
  // 저장하면 서버가 공고를 다시 판정한다. 내 정보(입력 개수)는 실패해도 저장 결과에 영향이 없게 따로 다시 받는다
  const submitProfile = async (next: Profile) => {
    setSavingProfile(true);
    setProfileError(null);
    try {
      setProfileOverride(await saveProfile(next));
      getMe().then(setMeOverride).catch(() => undefined);
      setProfileOpen(false);
      showToast("프로필을 바꿨어요. 공고를 다시 판정했어요");
    } catch (caught) {
      const consent = consentRequired(caught);
      if (consent === "terms_privacy") navigate({ name: "onboarding" });
      // 다른 곳에서 소득 동의를 철회했다: 내 정보를 다시 받아 소득 입력란을 닫는다
      if (consent === "income_info") getMe().then(setMeOverride).catch(() => undefined);
      setProfileError({ message: errorMessage(caught, PROFILE_FAILED), fields: fieldErrors(caught) as ProfileErrors });
    } finally {
      setSavingProfile(false);
    }
  };
  const removeAccount = async () => {
    setDeleteError(null);
    try {
      await deleteAccount();
      navigate({ name: "onboarding" });
    } catch (caught) {
      setDeleteError(errorMessage(caught, "탈퇴하지 못했어요. 잠시 후 다시 눌러 주세요."));
    }
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
          <Button secondary onClick={() => openProfile(true)}>수정</Button>
        </div>
        <div className="mt-4 grid grid-cols-5 gap-3 max-[900px]:grid-cols-2">
          {[
            ["학적", `${profile.department ?? "미입력"} · ${academicStatus || "미입력"}`],
            ["성적", profile.gpa_last_semester ? `${profile.gpa_last_semester} / ${profile.gpa_scale}` : "미입력"],
            ["나이", age ? `${age}세` : "미입력"],
            ["지역", regionText(profile)],
            ["소득", profile.income_bracket !== null ? `${profile.income_bracket}구간` : "미입력"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-[12px] bg-[#f7f8fa] p-3">
              <p className="text-[11px] text-[#667085]">{label}</p>
              <p className="mt-1 text-[13px] font-semibold">{value}</p>
            </div>
          ))}
        </div>
      </section>
      <ConnectedServices
        me={me}
        lms={request.data[3]}
        calendarResult={calendarResult}
        onMeChange={setMeOverride}
      />
      <NotificationSettings settings={settings} onChange={updateSettings} />
      <section className="rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <h2 className="text-[18px] font-semibold">계정</h2>
        <IncomeConsentSetting consented={me.income_info_consented} onChanged={async () => {
          setMeOverride(await getMe());
          setProfileOverride(await getProfile());
        }} />
        <button
          type="button"
          onClick={() => {
            setDeleteError(null);
            setDeleteOpen(true);
          }}
          className="mt-4 text-[13px] font-semibold text-[#c53030]"
        >
          탈퇴
        </button>
      </section>
      <Modal open={profileOpen} title="프로필 수정" onClose={() => openProfile(false)}>
        <ProfileForm
          profile={profile}
          departments={departments}
          incomeConsented={me.income_info_consented}
          saving={savingProfile}
          serverErrors={profileError?.fields}
          error={profileError?.message}
          onCancel={() => openProfile(false)}
          onSave={submitProfile}
        />
      </Modal>
      <Modal open={deleteOpen} title="계정 탈퇴" onClose={() => setDeleteOpen(false)}>
        {DELETE_ACCOUNT_READY ? (
          <>
            <p className="text-[14px] leading-6 text-[#344054]">
              모든 개인 정보와 토큰을 지워요. 공유한 포스터 공고는 이름 없이 남아요.
            </p>
            <label className="mt-4 block text-[13px] font-semibold">
              확인을 위해 탈퇴를 입력해 주세요
              <input value={deleteText} onChange={(event) => setDeleteText(event.target.value)} className="mt-2 h-[42px] w-full rounded-[10px] border border-[#e5e7eb] px-3 outline-none focus:border-[#c53030]" />
            </label>
            {deleteError && <p role="alert" className="mt-3 text-[13px] text-[#c53030]">{deleteError}</p>}
            <div className="mt-6 flex justify-end gap-2">
              <Button secondary onClick={() => setDeleteOpen(false)}>취소</Button>
              <Button disabled={deleteText !== "탈퇴"} onClick={removeAccount}>탈퇴</Button>
            </div>
          </>
        ) : (
          <>
            {/* TODO(api): DELETE /me가 생기면 지운다 */}
            <p className="text-[14px] leading-6 text-[#344054]">
              탈퇴는 아직 준비 중이에요. 준비되면 이 화면에서 바로 탈퇴할 수 있어요.
            </p>
            <div className="mt-6 flex justify-end">
              <Button onClick={() => setDeleteOpen(false)}>확인</Button>
            </div>
          </>
        )}
      </Modal>
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          {toast}
        </div>
      )}
    </>
  );
}
