import Badge from "@/components/Badge";
import DownloadButton from "@/components/DownloadButton";
import { formatFileSize } from "@/lib/format";
import type {
  AnnouncementAttachment,
  AnnouncementCategory,
  AttachmentStatus,
  CourseDetail,
} from "@/types/api";
import type { Route, Tone } from "@/types/route";

interface CourseAnnouncementsProps {
  announcements: CourseDetail["announcements"];
  navigate: (route: Route) => void;
  onToast: (message: string) => void; // 첨부를 받지 못했을 때
}

const categoryMeta: Record<
  AnnouncementCategory | "general",
  { label: string; tone: Tone }
> = {
  schedule_change: { label: "일정 변경", tone: "yellow" },
  material: { label: "자료 배포", tone: "blue" },
  opportunity: { label: "기회", tone: "green" },
  general: { label: "일반", tone: "gray" },
};

// 공지 첨부의 내 저장 상태(F-54). 동기화가 내 문서함에 받는다. 저장된 첨부는 여기서 바로 받는다(F-44)
const attachmentMeta: Record<
  AttachmentStatus,
  { label: string; tone: Tone; note?: string }
> = {
  saved: { label: "저장됨", tone: "green" },
  too_large: {
    label: "저장 안 함",
    tone: "gray",
    note: "20MB가 넘어 저장하지 않았어요. LMS에서 받아 주세요.",
  },
  pending: { label: "저장 전", tone: "gray", note: "다음 동기화 때 저장해요." },
};

function AnnouncementAttachments({
  attachments,
  onToast,
}: {
  attachments: AnnouncementAttachment[];
  onToast: (message: string) => void;
}) {
  if (attachments.length === 0) return null;
  return (
    <ul className="mt-3 flex flex-col gap-2" aria-label="첨부 파일">
      {attachments.map((file, index) => {
        const meta = attachmentMeta[file.status];
        const size = formatFileSize(file.size_bytes);
        return (
          <li
            key={`${index}-${file.name}`}
            className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]"
          >
            <span className="text-[#667085]">첨부</span>
            <span className="break-all font-medium text-[#344054]">
              {file.name}
            </span>
            {size && <span className="text-[#a0a4ab]">{size}</span>}
            <Badge tone={meta.tone}>{meta.label}</Badge>
            {meta.note && <span className="text-[#667085]">{meta.note}</span>}
            {file.status === "saved" && file.file_id && (
              <DownloadButton fileId={file.file_id} fileName={file.name} onError={onToast} compact />
            )}
          </li>
        );
      })}
    </ul>
  );
}

export default function CourseAnnouncements({
  announcements,
  navigate,
  onToast,
}: CourseAnnouncementsProps) {
  return (
    <div className="flex flex-col gap-3">
      {announcements.map((announcement) => {
        const category = categoryMeta[announcement.category ?? "general"];
        return (
          <article
            key={announcement.id}
            className="rounded-[12px] bg-[#f7f8fa] p-4"
          >
            <div className="flex items-center gap-2">
              <p className="text-[14px] font-semibold">{announcement.title}</p>
              <Badge tone={category.tone}>{category.label}</Badge>
            </div>
            <p className="mt-2 truncate text-[12px] text-[#667085]">
              {announcement.summary ?? "공지 내용을 LMS에서 확인해 주세요."}
            </p>
            <AnnouncementAttachments attachments={announcement.attachments} onToast={onToast} />
            {announcement.category === "opportunity" &&
              announcement.opportunity_id && (
                <button
                  type="button"
                  onClick={() =>
                    navigate({
                      name: "opportunity",
                      id: announcement.opportunity_id!,
                    })
                  }
                  className="mt-3 text-[12px] font-semibold text-[#4f6ef7]"
                >
                  공고로 보기
                </button>
              )}
          </article>
        );
      })}
    </div>
  );
}
