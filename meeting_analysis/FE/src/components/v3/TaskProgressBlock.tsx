import type { Citation, ProgressStep, TaskOut, TaskProgress } from "../../api/types";
import { quotesOf, type TranscriptIndex } from "../../lib/citations";
import { formatDate, formatDue, targetName, topicNumber } from "../../lib/format";
import { CitationCount, EmptyState, EvidenceItem, SectionLabel } from "../agentic/primitives";

const STATUS_LABEL: Record<string, string> = {
  done: "Đã xong",
  in_progress: "Đang làm",
  blocked: "Vướng mắc",
  returned: "Phải làm lại",
  deferred: "Hoãn / chờ",
  mentioned: "Chỉ nhắc tới",
  not_reported: "Không được báo cáo",
  not_started: "Chưa làm",
};

const STATUS_CLASS: Record<string, string> = {
  done: "tag tag-ok",
  in_progress: "tag tag-neutral",
  blocked: "tag tag-accent",
  returned: "tag tag-accent",
  deferred: "tag tag-outline",
  mentioned: "tag tag-muted",
  not_reported: "tag tag-muted",
};

const MERGED_LABEL: Record<string, { label: string; title: string }> = {
  reassign: { label: "Giao lại", title: "Cuộc họp giao việc này cho bên khác bên chủ trì/phối hợp cũ" },
  reschedule: { label: "Đổi hạn", title: "Cuộc họp đặt hạn mới khác hạn cũ" },
};

function statusLabel(status: string | null): string {
  return status ? (STATUS_LABEL[status] ?? status) : "—";
}

/** Hạn sau phiên họp: bỏ hạn, hạn mới, hoặc giữ hạn cũ. */
function dueText(task: TaskOut, progress: TaskProgress): string {
  const before = progress.previous_due ? formatDate(progress.previous_due) : "không có hạn";
  if (progress.deadline_removed) return `${before} → bỏ hạn`;
  const due = task.extracted.due;
  if (due && (due.raw || due.date !== progress.previous_due)) return `${before} → ${formatDue(due)}`;
  return before;
}

function updateNote(update: ProgressStep): string | null {
  if (update.status_flag === "revised") return `agent khai “${statusLabel(update.proposed_status)}”, Decisions sửa`;
  if (update.status_flag === "uncertain") return `agent khai “${statusLabel(update.proposed_status)}”, chưa xác nhận`;
  if (update.status_flag === "kept") return "Decisions chỉ xác nhận là báo cáo, giữ trạng thái agent khai";
  if (update.verification === "unchecked") return "chưa kiểm bằng Decisions";
  return null;
}

interface TaskProgressBlockProps {
  /** Việc cũ trong danh sách cần báo cáo (``extracted.progress`` khác null). */
  tasks: TaskOut[];
  topicIndexById: Record<string, number>;
  transcript: TranscriptIndex;
  selectedKey: string | null;
  onSelect: (key: string, citation: Citation) => void;
}

// Tab "Tiến độ": mỗi việc cũ một thẻ, kèm lời giao lại/dời hạn đã gộp và các cập nhật theo chủ
// đề (bấm để tô bằng chứng). Trạng thái lấy theo cập nhật quyết định ở backend: lượt chỉ
// đạo/kết luận thắng lượt báo cáo, cùng loại thì lượt muộn hơn thắng.
export function TaskProgressBlock({ tasks, topicIndexById, transcript, selectedKey, onSelect }: TaskProgressBlockProps) {
  if (tasks.length === 0) return <EmptyState>Request không có danh sách việc cần báo cáo.</EmptyState>;

  const counts = tasks.reduce<Record<string, number>>((acc, task) => {
    const status = task.extracted.progress!.status;
    acc[status] = (acc[status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-[12.5px] text-neutral-700">
        {Object.entries(counts)
          .map(([status, count]) => `${count} ${statusLabel(status).toLowerCase()}`)
          .join(" · ")}
      </p>
      {tasks.map((task) => {
        const progress = task.extracted.progress!;
        const owner = targetName(task.extracted.assignment.primary) ?? "chưa rõ";
        const reassigned = task.extensions.merged_relations.includes("reassign");
        return (
          <section key={task.task_id} className="bg-surface">
            <header className="flex flex-wrap items-start gap-3 border-b border-divider px-4 py-3">
              <span className="flex-none bg-neutral-200 px-1.5 py-0.5 font-mono text-[12px]">{task.task_id}</span>
              <div className="min-w-0 flex-1">
                <div className="font-heading text-[15px] leading-snug font-extrabold">{task.extracted.content.title}</div>
                <div className="mt-0.5 text-[11.5px] text-neutral-700">
                  {reassigned ? "Giao lại cho" : "Chủ trì"}: {owner} · Hạn: {dueText(task, progress)}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {progress.previous_status && (
                  <span className="text-[11.5px] text-neutral-600">{statusLabel(progress.previous_status)} →</span>
                )}
                <span className={STATUS_CLASS[progress.status] ?? "tag tag-neutral"}>{statusLabel(progress.status)}</span>
                {[...new Set(task.extensions.merged_relations)].map((relation) =>
                  MERGED_LABEL[relation] ? (
                    <span key={relation} className="tag tag-neutral" title={MERGED_LABEL[relation].title}>
                      {MERGED_LABEL[relation].label}
                    </span>
                  ) : null,
                )}
                {progress.status_conflict && (
                  <span className="tag tag-accent" title="Có báo cáo đã xong nhưng một cập nhật đã xác nhận khác nêu trạng thái khác">
                    mâu thuẫn
                  </span>
                )}
                {progress.uncertain && (
                  <span className="tag tag-outline" title="Decisions không xác nhận trạng thái agent khai">
                    chưa xác nhận
                  </span>
                )}
                {progress.overdue && (
                  <span className="tag tag-accent" title="Hạn cũ đã qua so với ngày họp mà việc chưa xong">
                    quá hạn
                  </span>
                )}
              </div>
            </header>

            {progress.updates.length === 0 ? (
              <p className="m-0 px-4 py-3 text-[12.5px] text-neutral-600">
                {task.extensions.merged_relations.length > 0
                  ? "Cuộc họp giao lại/đổi hạn việc này nhưng không báo cáo tiến độ."
                  : "Không chủ đề nào nói tới việc này."}
              </p>
            ) : (
              <div className="p-1.5">
                {(progress.directive || progress.blockers.length > 0) && (
                  <div className="px-3 pt-1.5 pb-2 text-[12.5px] leading-snug">
                    {progress.directive && (
                      <div>
                        <span className="text-neutral-600">Chỉ đạo: </span>
                        {progress.directive}
                      </div>
                    )}
                    {progress.blockers.length > 0 && (
                      <div>
                        <span className="text-neutral-600">Vướng mắc: </span>
                        {progress.blockers.join("; ")}
                      </div>
                    )}
                  </div>
                )}
                <div className="px-3 pt-1">
                  <SectionLabel>Cập nhật theo chủ đề</SectionLabel>
                </div>
                <ol className="m-0 list-none p-0">
                  {progress.updates.map((update, idx) => {
                    const key = `tasks:progress:${task.task_id}:${idx}`;
                    const topicIndex = topicIndexById[update.topic_id];
                    const note = updateNote(update);
                    return (
                      <li key={key}>
                        <EvidenceItem
                          selected={key === selectedKey}
                          onSelect={() => onSelect(key, { segmentIds: update.segment_ids, turnIds: update.turn_ids })}
                          quotes={quotesOf(transcript, update.segment_ids)}
                          trailing={<CitationCount count={update.segment_ids.length} />}
                          meta={
                            <>
                              <span className={STATUS_CLASS[update.status] ?? "tag tag-neutral"}>{statusLabel(update.status)}</span>
                              {update.deciding && progress.updates.length > 1 && (
                                <span className="tag tag-ok">quyết định trạng thái</span>
                              )}
                              {update.p_directive !== null && update.p_directive >= 0.8 && (
                                <span className="tag tag-outline" title={`p = ${update.p_directive.toFixed(2)}`}>
                                  lượt chỉ đạo
                                </span>
                              )}
                              {topicIndex !== undefined && <span className="tag tag-muted">Chủ đề {topicNumber(topicIndex)}</span>}
                              {update.due && <span className="tag tag-outline">Hạn mới: {formatDue(update.due)}</span>}
                              {update.deadline_removed && <span className="tag tag-outline">bỏ hạn</span>}
                              {note && (
                                <span className="tag tag-outline max-w-[320px] truncate" title={update.reason || note}>
                                  {note}
                                </span>
                              )}
                            </>
                          }
                        >
                          {update.summary || statusLabel(update.status)}
                        </EvidenceItem>
                      </li>
                    );
                  })}
                </ol>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
