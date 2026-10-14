import { errorMessage, setDocumentDone, TASKS_READY } from "@/api/client";
import { webUrl } from "@/lib/webUrl";
import type { DocumentItem, OpportunityDetail } from "@/types/api";

interface OpportunityDocumentsProps {
  detail: OpportunityDetail;
  onChange: (detail: OpportunityDetail) => void;
  onError: (message: string) => void;
}

function documentInfo(document: DocumentItem): string {
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

// 공고 상세의 필요 서류(준비하면 플래너 할 일과 같이 체크)와 공고 첨부파일
export default function OpportunityDocuments({ detail, onChange, onError }: OpportunityDocumentsProps) {
  // 서류 체크는 준비 일정을 만든 뒤에 한다. 실제 모드는 플래너 API 전까지 체크를 막는다
  const checkable = detail.prep.prepared && TASKS_READY;
  const lockedHint = detail.prep.prepared ? "서류 체크는 아직 준비 중이에요" : "준비 일정을 만들면 체크할 수 있어요";

  return (
    <div className="min-h-[400px] rounded-2xl border border-[#e5e7eb] bg-white p-[22px]">
      <h2 className="text-[18px] font-semibold">필요 서류</h2>
      <p className="mt-2 text-[13px] text-[#667085]">발급 방법과 예상 시간을 확인하세요.</p>
      <div className="mt-4 flex flex-col gap-[14px]">
        {detail.documents.length === 0 && (
          <p className="text-[13px] text-[#667085]">공고에서 정리한 제출 서류가 없어요. 원문을 확인해 주세요.</p>
        )}
        {detail.documents.map((document) => {
          const formUrl = webUrl(document.form_url);
          return (
            <div key={document.id}>
              <label
                title={checkable ? undefined : lockedHint}
                className={`text-[14px] font-semibold ${checkable ? "cursor-pointer" : "cursor-not-allowed"}`}
              >
                <input
                  type="checkbox"
                  checked={document.is_done === true}
                  disabled={!checkable}
                  onChange={async (event) => {
                    try {
                      onChange(await setDocumentDone(detail.id, document.id, event.target.checked));
                    } catch (caught) {
                      onError(errorMessage(caught, "서류를 체크하지 못했어요. 잠시 후 다시 눌러 주세요."));
                    }
                  }}
                  className="mr-2 accent-[#4f6ef7]"
                />
                {document.name}
              </label>
              <p className="ml-5 text-[12px] text-[#667085]">
                {documentInfo(document)}
                {document.how_to && <span className="block">{document.how_to}</span>}
                {formUrl && (
                  <a href={formUrl} target="_blank" rel="noopener noreferrer" className="ml-2 font-semibold text-[#4f6ef7]">양식 내려받기</a>
                )}
              </p>
              {!checkable && <p className="ml-5 mt-1 text-[11px] text-[#a0a4ab]">{lockedHint}</p>}
            </div>
          );
        })}
      </div>
      {detail.attachments.length > 0 && (
        <div className="mt-6 border-t border-[#e5e7eb] pt-4">
          <h3 className="text-[14px] font-semibold">공고 첨부파일</h3>
          <ul className="mt-2 flex flex-col gap-2">
            {detail.attachments.map((attachment) => {
              const url = webUrl(attachment.source_url);
              return (
                <li key={attachment.id} className="text-[13px]">
                  {url ? (
                    <a href={url} target="_blank" rel="noopener noreferrer" className="font-semibold text-[#4f6ef7]">{attachment.file_name}</a>
                  ) : (
                    <span className="font-semibold">{attachment.file_name}</span>
                  )}
                  {attachment.extract_status === "failed" && (
                    <span className="ml-2 text-[12px] text-[#667085]">AI가 읽지 못한 파일이에요</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
