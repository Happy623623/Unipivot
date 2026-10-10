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
  onToggle: (task: PlannerTask) => void;
  onAdd: (title: string, date: string) => Promise<void>;
  onEdit: (id: string, title: string, date: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
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

  const openForm = (task?: PlannerTask) => {
    setEditing(task ?? null);
    setTitle(task?.title ?? "");
    setDueDate(task?.due_date ?? date);
    setModalOpen(true);
    setMenuOpen(null);
  };

  const save = async () => {
    if (!title.trim()) return;
    setSaving(true);
    if (editing) await onEdit(editing.id, title.trim(), dueDate);
    else await onAdd(title.trim(), dueDate);
    setSaving(false);
    setModalOpen(false);
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
                      onChange={() => onToggle(task)}
                      className="mt-1 accent-[#4f6ef7]"
                    />
                    <span>
                      <b className={`block text-[14px] ${task.is_done ? "text-[#a0a4ab] line-through" : ""}`}>{task.title}</b>
                      {task.auto_completed && <span className="mt-1 block text-[11px] text-[#15803d]">제출 확인됨</span>}
                    </span>
                  </label>
                  <div className="flex items-center gap-2">
                    <Badge tone={meta.tone}>{meta.label}</Badge>
                    {task.source === "manual" && (
                      <button type="button" onClick={() => setMenuOpen(menuOpen === task.id ? null : task.id)} className="px-1 text-[18px] text-[#667085]">⋯</button>
                    )}
                  </div>
                </div>
                {menuOpen === task.id && (
                  <div className="absolute right-3 top-11 z-10 w-24 rounded-[10px] border border-[#e5e7eb] bg-white p-1 shadow-lg">
                    <button type="button" onClick={() => openForm(task)} className="block w-full rounded-[8px] px-3 py-2 text-left text-[12px] hover:bg-[#f7f8fa]">수정</button>
                    <button type="button" onClick={async () => {
                      await onDelete(task.id);
                      setMenuOpen(null);
                    }} className="block w-full rounded-[8px] px-3 py-2 text-left text-[12px] text-[#c53030] hover:bg-[#fef2f2]">삭제</button>
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
      <Modal open={modalOpen} title={editing ? "일정 수정" : "일정 추가"} onClose={() => setModalOpen(false)}>
        <label>
          <span className="mb-2 block text-[13px] font-semibold">제목</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} className="h-[42px] w-full rounded-[10px] border border-[#e5e7eb] px-3 text-[14px] outline-none focus:border-[#4f6ef7]" />
        </label>
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
