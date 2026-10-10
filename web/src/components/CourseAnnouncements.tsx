import Badge from "@/components/Badge";
import type { AnnouncementCategory, CourseDetail } from "@/types/api";
import type { Route, Tone } from "@/types/route";

interface CourseAnnouncementsProps {
  announcements: CourseDetail["announcements"];
  navigate: (route: Route) => void;
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

export default function CourseAnnouncements({
  announcements,
  navigate,
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
