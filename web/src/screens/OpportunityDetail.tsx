import { useEffect, useState } from "react";
import { getOpportunity, reportOpportunity, setDocumentDone } from "@/api/client";
import AiProcessPanel from "@/components/AiProcessPanel";
import Header from "@/components/Header";
import Modal from "@/components/Modal";
import OpportunityConditions from "@/components/OpportunityConditions";
import OpportunityPreparation from "@/components/OpportunityPreparation";
import ProfileInputModal from "@/components/ProfileInputModal";
import ReportModal from "@/components/ReportModal";
import Skeleton from "@/components/Skeleton";
import { getCategoryLabel } from "@/lib/format";
import useAsyncData from "@/lib/useAsyncData";
import type { OpportunityDetail as OpportunityDetailData } from "@/types/api";
import type { Route } from "@/types/route";

interface OpportunityDetailProps {
  id: string;
  focus?: "profile_input";
  calendarConnected: boolean;
  navigate: (route: Route) => void;
}

function DetailSkeleton() {
  return (
    <>
      <Skeleton className="h-[70px] w-[480px]" />
      <Skeleton className="h-[150px] w-full rounded-2xl" />
      <div className="grid grid-cols-[1.3fr_1fr] gap-5">
        <Skeleton className="h-[400px] rounded-2xl" />
        <Skeleton className="h-[400px] rounded-2xl" />
      </div>
    </>
  );
}

function documentInfo(document: OpportunityDetailData["documents"][number]): string {
  const issuer = document.issuer ?? "발급처 확인";
  let info =
    document.lead_days === 0
      ? `${issuer} · 즉시 발급`
      : document.lead_days
        ? `${issuer} · 발급 ${document.lead_days}일`
        : issuer;
  if (document.effort_minutes) info += ` · 작성 약 ${document.effort_minutes}분`;
  return info;
}

export default function OpportunityDetail({
  id,
  focus,
  calendarConnected,
  navigate,
}: OpportunityDetailProps) {
  const request = useAsyncData(() => getOpportunity(id), [id]);
  const [override, setOverride] = useState<OpportunityDetailData | null>(null);
  const [profileOpen, setProfileOpen] = useState(focus === "profile_input");
  const [posterOpen, setPosterOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reported, setReported] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    setOverride(null);
    setProfileOpen(focus === "profile_input");
  }, [id, focus]);

  if (request.loading) return <DetailSkeleton />;
  if (request.error || !request.data) {
    return (
      <p className="rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        {request.error ?? "공고를 불러오지 못했어요."}
      </p>
    );
  }

  const detail = override ?? request.data;
  const isPoster = detail.source_type === "poster";
  const openOriginal = () => {
    if (isPoster) {
      if (detail.poster_url) setPosterOpen(true);
      return;
    }
    if (detail.original_url) window.open(detail.original_url, "_blank", "noopener,noreferrer");
  };
  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(""), 2200);
  };

  const saveProfile = (values: Record<string, string>) => {
    setSaving(true);
    setTimeout(() => {
      const missingFields = detail.eligibility.missing_fields;
      setOverride({
        ...detail,
        eligibility: {
          ...detail.eligibility,
          status: "eligible",
          display_status: "eligible",
          summary: "입력한 정보로 다시 판정했어요. 모든 조건을 충족해요.",
          reason_text: null,
          missing_fields: [],
          evaluated_at: "2026-10-05T10:00:00+09:00",
          conditions: detail.eligibility.conditions.map((condition) =>
            missingFields.includes(condition.field)
              ? {
                  ...condition,
                  user_value: values[condition.field] || "입력 완료",
                  user_value_text: values[condition.field] || "입력 완료",
                  outcome: "pass",
                }
              : condition,
          ),
        },
      });
      setSaving(false);
      setProfileOpen(false);
      showToast("다시 판정했어요");
    }, 800);
  };

  const originalAction =
    isPoster || detail.original_url ? (
      <button type="button" onClick={openOriginal} className="text-[13px] font-semibold text-[#4f6ef7]">원문 보기</button>
    ) : null;

  return (
    <>
      <Header
        title={detail.title}
        subtitle={`${getCategoryLabel(detail.category, "detail")} · ${detail.organizer ?? "주최 미정"}`}
        action={originalAction}
      />
      <OpportunityPreparation
        detail={detail}
        calendarConnected={calendarConnected}
        navigate={navigate}
        onOpenProfile={() => setProfileOpen(true)}
        onOpenOriginal={openOriginal}
        onDetailChange={setOverride}
      />
      {isPoster && (
        <section className="flex items-center justify-between rounded-[14px] border border-[#e5e7eb] bg-white px-[18px] py-3">
          <p className="text-[13px] text-[#667085]">{detail.uploader_masked}님이 공유한 포스터예요</p>
          <button
            type="button"
            disabled={reported || detail.reported_by_me}
            onClick={() => setReportOpen(true)}
            className="text-[13px] font-semibold text-[#667085] disabled:cursor-default disabled:text-[#a0a4ab]"
          >
            {reported || detail.reported_by_me ? "신고함" : "신고"}
          </button>
        </section>
      )}
      <section className="grid grid-cols-[1.3fr_1fr] gap-5 max-[900px]:grid-cols-1">
        <div className="min-h-[400px] rounded-2xl border border-[#e5e7eb] bg-white p-[22px]">
          <h2 className="text-[18px] font-semibold">AI 자격 판정</h2>
          <p className="mt-2 text-[13px] text-[#667085]">행을 누르면 판정에 사용한 공고 원문을 확인할 수 있어요.</p>
          <OpportunityConditions
            conditions={detail.eligibility.conditions}
            ineligible={detail.eligibility.display_status === "ineligible"}
          />
        </div>
        <div className="min-h-[400px] rounded-2xl border border-[#e5e7eb] bg-white p-[22px]">
          <h2 className="text-[18px] font-semibold">필요 서류</h2>
          <p className="mt-2 text-[13px] text-[#667085]">발급 방법과 예상 시간을 확인하세요.</p>
          <div className="mt-4 flex flex-col gap-[14px]">
            {detail.documents.map((document) => (
              <div key={document.id}>
                <label
                  title={detail.prep.prepared ? undefined : "준비 일정을 만들면 체크할 수 있어요"}
                  className={`text-[14px] font-semibold ${detail.prep.prepared ? "cursor-pointer" : "cursor-not-allowed"}`}
                >
                  <input
                    type="checkbox"
                    checked={document.is_done === true}
                    disabled={!detail.prep.prepared}
                    onChange={async (event) => {
                      const updated = await setDocumentDone(detail.id, document.id, event.target.checked);
                      setOverride(updated);
                    }}
                    className="mr-2 accent-[#4f6ef7]"
                  />
                  {document.name}
                </label>
                <p className="ml-5 text-[12px] text-[#667085]">
                  {documentInfo(document)}
                  {document.form_url && (
                    <a href={document.form_url} target="_blank" rel="noreferrer" className="ml-2 font-semibold text-[#4f6ef7]">양식 내려받기</a>
                  )}
                </p>
                {!detail.prep.prepared && (
                  <p className="ml-5 mt-1 text-[11px] text-[#a0a4ab]">준비 일정을 만들면 체크할 수 있어요</p>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>
      <AiProcessPanel detail={detail} />
      <ProfileInputModal
        open={profileOpen}
        missingFields={detail.eligibility.missing_fields}
        conditions={detail.eligibility.conditions}
        saving={saving}
        onClose={() => setProfileOpen(false)}
        onSave={saveProfile}
      />
      <Modal open={posterOpen} title="포스터 원문" onClose={() => setPosterOpen(false)}>
        {detail.poster_url && <img src={detail.poster_url} alt={`${detail.title} 포스터`} className="mx-auto max-h-[70dvh] rounded-[14px]" />}
      </Modal>
      <ReportModal
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        onSubmit={async (reason, detailText) => {
          await reportOpportunity(detail.id, reason, detailText);
          setReported(true);
          setReportOpen(false);
          showToast("신고했어요");
        }}
      />
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          {toast}
        </div>
      )}
    </>
  );
}
