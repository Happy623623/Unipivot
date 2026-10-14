import { useState } from "react";
import Badge from "@/components/Badge";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import { formatKstLongDate } from "@/lib/format";
import { getPlannerTaskMeta } from "@/lib/planner";
import type { PlannerMarker, PlannerTask } from "@/types/api";

interface PlannerDayPanelProps {
  date: string;
  tasks: PlannerTask[];
  markers: PlannerMarker[];
  onToggle: (task: PlannerTask) => Promise<void>;
  onAdd: (title: string, date: string) => Promise<void>;
  onEdit: (task: PlannerTask, title: string, date: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

// 고칠 수 있는 범위는 출처가 정한다(API 명세 7장). 직접 추가한 할 일만 제목까지 고치고 지운다.
// 준비·강의계획서 할 일은 날짜만 옮기고, LMS 할 일은 완료만 바꾼다
function editable(task: PlannerTask): { title: boolean; date: boolean; remove: boolean } {
  if (task.source === "manual") return { title: true, date: true, remove: true };
  if (task.source === "prep_plan" || task.source === "syllabus") {
    return { title: false, date: true, remove: false };
  }
  return { title: false, date: false, remove: false };
}

export default function PlannerDayPanel({
  date,
  tasks,
  markers,
  onToggle,
  onAdd,
  onEdit,
  onDelete,
}: PlannerDayPanelProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<PlannerTask | null>(null);
  const [title, setTitle] = useState("");
  const [dueDate, setDueDate] = useState(date);
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);

  const openForm = (task?: PlannerTask) => {
    setEditing(task ?? null);
    setTitle(task?.title ?? "");
    setDueDate(task?.due_date ?? date);
    setModalOpen(true);
    setMenuOpen(null);
  };

  const canEditTitle = !editing || editable(editing).title;

  const save = async () => {
    if (canEditTitle && !title.trim()) return;
    setSaving(true);
    try {
      if (editing) await onEdit(editing, title.trim(), dueDate);
      else await onAdd(title.trim(), dueDate);
      setModalOpen(false); // 저장하지 못하면(오류가 올라온다) 창을 열어 둔 채 다시 누르게 한다
    } catch {
      /* 안내는 화면이 띄운다 */
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="min-h-[650px] rounded-2xl border border-[#e5e7eb] bg-white p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[20px] font-bold">{formatKstLongDate(date)}</h2>
            <p className="mt-1 text-[12px] text-[#667085]">할 일 {tasks.length}개</p>
          </div>
          <button type="button" onClick={() => openForm()} className="text-[13px] font-semibold text-[#4f6ef7]">+ 일정 추가</button>
        </div>
        <hr className="my-4 border-[#e5e7eb]" />
        <div className="flex flex-col gap-3">
          {tasks.map((task) => {
            const meta = getPlannerTaskMeta(task);
            return (
              <article key={task.id} className="relative rounded-xl bg-[#f7f8fa] p-[14px]">
                <div className="flex items-start justify-between gap-2">
                  <label className="flex min-w-0 cursor-pointer items-start gap-2">
                    <input
                      type="checkbox"
                      checked={task.is_done}
                      disabled={toggling === task.id}
                      onChange={async () => {
                        setToggling(task.id); // 연타하면 응답 순서가 엇갈린다
                        try {
                          await onToggle(task);
                        } finally {
                          setToggling(null);
                        }
                      }}
                      className="mt-1 accent-[#4f6ef7]"
                    />
                    <span>
                      <b className={`block text-[14px] ${task.is_done ? "text-[#a0a4ab] line-through" : ""}`}>{task.title}</b>
                      {task.auto_completed && <span className="mt-1 block text-[11px] text-[#15803d]">제출 확인됨</span>}
                    </span>
                  </label>
                  <div className="flex items-center gap-2">
                    <Badge tone={meta.tone}>{meta.label}</Badge>
                    {(editable(task).title || editable(task).date) && (
                      <button type="button" onClick={() => setMenuOpen(menuOpen === task.id ? null : task.id)} aria-label={`${task.title} 더 보기`} className="px-1 text-[18px] text-[#667085]">⋯</button>
                    )}
                  </div>
                </div>
                {menuOpen === task.id && (
                  <div className="absolute right-3 top-11 z-10 w-28 rounded-[10px] border border-[#e5e7eb] bg-white p-1 shadow-lg">
                    <button type="button" onClick={() => openForm(task)} className="block w-full rounded-[8px] px-3 py-2 text-left text-[12px] hover:bg-[#f7f8fa]">
                      {editable(task).title ? "수정" : "날짜 옮기기"}
                    </button>
                    {editable(task).remove && (
                      <button type="button" onClick={async () => {
                        await onDelete(task.id);
                        setMenuOpen(null);
                      }} className="block w-full rounded-[8px] px-3 py-2 text-left text-[12px] text-[#c53030] hover:bg-[#fef2f2]">삭제</button>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
        {markers.length > 0 && (
          <div className="mt-5">
            <h3 className="text-[13px] font-semibold text-[#667085]">마감</h3>
            <div className="mt-2 flex flex-col gap-2">
              {markers.map((marker) => (
                <div key={marker.opportunity_id} className="rounded-[10px] border border-[#4f6ef7] px-3 py-2 text-[12px] font-semibold text-[#4f6ef7]">
                  {marker.title} · 마감
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      <Modal
        open={modalOpen}
        title={!editing ? "일정 추가" : canEditTitle ? "일정 수정" : "날짜 옮기기"}
        onClose={() => setModalOpen(false)}
      >
        {canEditTitle ? (
          <label>
            <span className="mb-2 block text-[13px] font-semibold">제목</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={120} className="h-[42px] w-full rounded-[10px] border border-[#e5e7eb] px-3 text-[14px] outline-none focus:border-[#4f6ef7]" />
          </label>
        ) : (
          <div>
            <p className="text-[14px] font-semibold">{editing?.title}</p>
            <p className="mt-1 text-[12px] text-[#667085]">공고 준비 일정이라 제목은 바꿀 수 없어요. 날짜만 옮겨요.</p>
          </div>
        )}
        <label className="mt-4 block">
          <span className="mb-2 block text-[13px] font-semibold">날짜</span>
          <input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} className="h-[42px] w-full rounded-[10px] border border-[#e5e7eb] px-3 text-[14px] outline-none focus:border-[#4f6ef7]" />
        </label>
        <div className="mt-6 flex justify-end gap-2">
          <Button secondary onClick={() => setModalOpen(false)}>취소</Button>
          <Button onClick={save} disabled={saving}>{saving ? "저장 중" : "저장"}</Button>
        </div>
      </Modal>
    </>
  );
}
