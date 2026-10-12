import { useEffect, useState } from "react";
import { errorMessage, getOpportunity } from "@/api/client";
import Button from "@/components/Button";
import AiProcessPanel from "@/components/AiProcessPanel";
import Header from "@/components/Header";
import Modal from "@/components/Modal";
import OpportunityConditions from "@/components/OpportunityConditions";
import OpportunityDocuments from "@/components/OpportunityDocuments";
import OpportunityPreparation from "@/components/OpportunityPreparation";
import ProfileInputModal from "@/components/ProfileInputModal";
import Skeleton from "@/components/Skeleton";
import { getCategoryLabel } from "@/lib/format";
import useAsyncData from "@/lib/useAsyncData";
import { webUrl } from "@/lib/webUrl";
import type { OpportunityDetail as OpportunityDetailData, OpportunityStatus } from "@/types/api";
import type { Route } from "@/types/route";

interface OpportunityDetailProps {
  id: string;
  focus?: "profile_input";
  calendarConnected: boolean;
  navigate: (route: Route) => void;
}

// 준비한 공고는 마감·숨김·병합이 되어도 본인에게 보인다. 그때 화면 위에 띄우는 안내 (API 명세 5장 status)
const STATUS_NOTICE: Record<Exclude<OpportunityStatus, "active">, string> = {
  expired: "마감된 공고예요.",
  hidden: "지금은 목록에서 내린 공고예요.",
  merged: "같은 내용의 다른 공고와 합쳐진 공고예요.",
};

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

export default function OpportunityDetail({
  id,
  focus,
  calendarConnected,
  navigate,
}: OpportunityDetailProps) {
  const request = useAsyncData(
    () =>
      getOpportunity(id).catch((error: unknown) => {
        throw new Error(errorMessage(error, "공고를 불러오지 못했어요. 잠시 후 다시 열어 주세요."));
      }),
    [id],
  );
  const [override, setOverride] = useState<OpportunityDetailData | null>(null);
  const [profileOpen, setProfileOpen] = useState(focus === "profile_input");
  const [posterOpen, setPosterOpen] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    setOverride(null);
    setProfileOpen(focus === "profile_input");
  }, [id, focus]);

  if (request.loading) return <DetailSkeleton />;
  if (request.error || !request.data) {
    return (
      <div className="flex items-center justify-between gap-4 rounded-[14px] bg-[#fef2f2] p-4 text-[#c53030]">
        <p>{request.error ?? "공고를 불러오지 못했어요."}</p>
        <Button secondary onClick={() => navigate({ name: "home" })}>홈으로</Button>
      </div>
    );
  }

  const detail = override ?? request.data;
  const isPoster = detail.source_type === "poster";
  // 포스터는 원본 이미지(포스터 업로드 W6부터)를 창으로, 나머지는 원문 주소를 새 탭으로 연다. 둘 다 없으면 원문 보기가 없다
  const originalHref = isPoster ? null : webUrl(detail.original_url);
  const openPoster = isPoster && detail.poster_url ? () => setPosterOpen(true) : null;
  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(""), 2200);
  };

  // 정보 입력을 저장한 뒤: 서버가 상세를 줄 때 지금 프로필로 다시 판정한다
  const reloadAfterProfile = async () => {
    try {
      const updated = await getOpportunity(id);
      setOverride(updated);
      setProfileOpen(false);
      showToast("다시 판정했어요");
    } catch {
      setProfileOpen(false);
      showToast("저장했어요. 화면을 새로 고치면 다시 판정한 결과가 보여요.");
    }
  };

  const subtitle = [
    getCategoryLabel(detail.category, "detail"),
    detail.organizer ?? "주최 미정",
    ...(isPoster && detail.uploaded_by_me ? ["내가 올린 포스터"] : []),
    ...(detail.course_name ? [`${detail.course_name} 수강생 대상`] : []),
  ].join(" · ");

  return (
    <>
      <Header
        title={detail.title}
        subtitle={subtitle}
        action={
          originalHref ? (
            <a href={originalHref} target="_blank" rel="noopener noreferrer" className="text-[13px] font-semibold text-[#4f6ef7]">원문 보기</a>
          ) : openPoster ? (
            <button type="button" onClick={openPoster} className="text-[13px] font-semibold text-[#4f6ef7]">원문 보기</button>
          ) : null
        }
      />
      {detail.status !== "active" && (
        <p role="status" className="rounded-[14px] border border-[#e5e7eb] bg-[#f2f4f7] px-[18px] py-3 text-[13px] font-semibold text-[#475467]">
          {STATUS_NOTICE[detail.status]}
          {detail.prep.prepared && " 준비한 서류와 일정은 그대로 볼 수 있어요."}
        </p>
      )}
      <OpportunityPreparation
        detail={detail}
        calendarConnected={calendarConnected}
        navigate={navigate}
        onOpenProfile={() => setProfileOpen(true)}
        originalHref={originalHref}
        onOpenPoster={openPoster}
        onDetailChange={setOverride}
      />
      <section className="grid grid-cols-[1.3fr_1fr] gap-5 max-[900px]:grid-cols-1">
        <div className="min-h-[400px] rounded-2xl border border-[#e5e7eb] bg-white p-[22px]">
          <h2 className="text-[18px] font-semibold">AI 자격 판정</h2>
          <p className="mt-2 text-[13px] text-[#667085]">행을 누르면 판정에 사용한 공고 원문을 확인할 수 있어요.</p>
          <OpportunityConditions eligibility={detail.eligibility} />
        </div>
        <OpportunityDocuments detail={detail} onChange={setOverride} onError={showToast} />
      </section>
      <AiProcessPanel detail={detail} />
      <ProfileInputModal
        open={profileOpen && detail.eligibility.missing_fields.length > 0}
        opportunityId={detail.id}
        missingFields={detail.eligibility.missing_fields}
        onClose={() => setProfileOpen(false)}
        onSaved={reloadAfterProfile}
      />
      <Modal open={posterOpen} title="포스터 원문" onClose={() => setPosterOpen(false)}>
        {detail.poster_url && <img src={detail.poster_url} alt={`${detail.title} 포스터`} className="mx-auto max-h-[70dvh] rounded-[14px]" />}
      </Modal>
      {toast && (
        <div className="fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-[10px] bg-[#181a20] px-4 py-3 text-[13px] font-semibold text-white">
          {toast}
        </div>
      )}
    </>
  );
}
