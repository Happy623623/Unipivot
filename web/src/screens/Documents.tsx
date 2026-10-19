import Button from "@/components/Button";
import DownloadButton from "@/components/DownloadButton";
import Header from "@/components/Header";
import { EmptyBox } from "@/components/HomeStates";
import Skeleton from "@/components/Skeleton";
import Toast from "@/components/Toast";
import { formatFileSize, formatKstDate } from "@/lib/format";
import useDocuments from "@/lib/useDocuments";
import useToast from "@/lib/useToast";
import type { MyFile } from "@/types/api";
import type { Route } from "@/types/route";

// 문서함 (F-44). 내 강의자료(공지 첨부 포함)·강의계획서를 과목별로 묶고, 받기를 누르면 원래 이름으로 내려받는다.
// 과목 묶음은 가장 최근 파일이 있는 과목부터이고, 과목을 모르는 파일은 맨 아래에 따로 모은다
interface CourseGroup {
  key: string;
  course: MyFile["course"];
  items: MyFile[];
}

// 받은 순서(최신순)를 지키며 과목끼리 묶는다
function courseGroups(items: MyFile[]): CourseGroup[] {
  const groups = new Map<string, CourseGroup>();
  items.forEach((item) => {
    const key = item.course?.id ?? "";
    const group = groups.get(key) ?? { key, course: item.course, items: [] };
    group.items.push(item);
    groups.set(key, group);
  });
  const all = [...groups.values()];
  return [...all.filter((group) => group.course), ...all.filter((group) => !group.course)];
}

function kindLabel(item: MyFile): string {
  if (item.kind === "syllabus") return "강의계획서";
  return item.origin === "lms_attachment" ? "공지 첨부" : "올린 강의자료";
}

function DocumentRow({ item, onError }: { item: MyFile; onError: (message: string) => void }) {
  const meta = [kindLabel(item), formatFileSize(item.size_bytes), formatKstDate(item.created_at)]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="flex items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="break-all text-[14px] font-semibold text-[#181a20]">{item.file_name}</p>
        <p className="mt-0.5 text-[12px] text-[#667085]">{meta}</p>
      </div>
      <DownloadButton fileId={item.file_id} fileName={item.file_name} onError={onError} />
    </li>
  );
}

function DocumentsSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-[164px] rounded-2xl" />
      <Skeleton className="h-[164px] rounded-2xl" />
    </div>
  );
}

export default function Documents({ navigate }: { navigate: (route: Route) => void }) {
  const { items, loading, error, hasMore, loadingMore, reload, loadMore } = useDocuments();
  const [toast, showToast] = useToast(3200);
  const groups = courseGroups(items);

  return (
    <>
      <Header title="문서함" subtitle="과목 공지 첨부와 강의계획서를 과목별로 모았어요. 받으면 원래 이름으로 저장돼요." />
      {loading && items.length === 0 && <DocumentsSkeleton />}
      {!loading && error !== null && items.length === 0 && (
        <EmptyBox title={error} action="다시 시도" onAction={reload} />
      )}
      {!loading && error === null && items.length === 0 && (
        <section className="flex flex-col items-center rounded-2xl border border-[#e5e7eb] bg-white p-8 text-center">
          <p className="text-[16px] font-semibold">아직 모인 자료가 없어요</p>
          <p className="mt-2 text-[13px] text-[#667085]">
            LearningX를 연결하면 과목 공지의 첨부가 여기에 모여요. 과목 화면에서 올린 강의계획서도 여기서 받을 수 있어요.
          </p>
          <div className="mt-5">
            <Button secondary onClick={() => navigate({ name: "academics" })}>
              학업으로 가기
            </Button>
          </div>
        </section>
      )}
      {groups.map((group) => (
        <section key={group.key} className="rounded-2xl border border-[#e5e7eb] bg-white px-5 pb-2 pt-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-[17px] font-semibold">
              {group.course?.short_name ?? "과목을 정하지 않은 파일"}
              <span className="ml-2 text-[13px] font-medium text-[#667085]">{group.items.length}개</span>
            </h2>
            {/* 수강을 뺀 과목은 과목 화면이 열리지 않아 링크를 두지 않는다(파일은 그대로 받는다) */}
            {group.course?.is_active && (
              <button
                type="button"
                onClick={() => navigate({ name: "course", id: group.course!.id })}
                aria-label={`${group.course.short_name} 과목 보기`}
                className="shrink-0 text-[12px] font-semibold text-[#4f6ef7]"
              >
                과목 보기&nbsp;<span aria-hidden="true"> →</span>
              </button>
            )}
          </div>
          <ul className="mt-1 divide-y divide-[#e5e7eb]">
            {group.items.map((item) => (
              <DocumentRow key={item.file_id} item={item} onError={showToast} />
            ))}
          </ul>
        </section>
      ))}
      {error !== null && items.length > 0 && <p className="text-[13px] text-[#c53030]">{error}</p>}
      {hasMore && (
        <div className="flex justify-center">
          <Button secondary onClick={loadMore} busy={loadingMore}>
            {loadingMore ? "불러오는 중…" : "더 보기"}
          </Button>
        </div>
      )}
      <Toast toast={toast} />
    </>
  );
}
