import type { ProgressUpdateOut, TaskProgressOut } from "../../api/types";
import { EmptyState, EvidenceItem, SectionLabel } from "../agentic/primitives";

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

function statusLabel(status: string | null): string {
  return status ? (STATUS_LABEL[status] ?? status) : "—";
}

/** "2026-01-31" -> "31/01/2026". */
function formatDate(iso: string | null): string {
  if (!iso) return "";
  const [year, month, day] = iso.split("-");
  return `${day}/${month}/${year}`;
}

/** Hạn sau phiên họp: bỏ hạn, ngày mới, hạn nguyên văn, hoặc giữ hạn cũ. */
function deadlineText(progress: TaskProgressOut): string {
  const before = progress.previous_due ? formatDate(progress.previous_due) : "không có hạn";
  if (progress.deadline_removed) return `${before} → bỏ hạn`;
  if (progress.deadline_date) return `${before} → ${formatDate(progress.deadline_date)}`;
  if (progress.deadline_raw) return `${before} → ${progress.deadline_raw}`;
  return before;
}

function updateNote(update: ProgressUpdateOut): string | null {
  if (update.status_flag === "revised") return `agent khai “${statusLabel(update.proposed_status)}”, Decisions sửa`;
  if (update.status_flag === "uncertain") return `agent khai “${statusLabel(update.proposed_status)}”, chưa xác nhận`;
  if (update.status_flag === "kept") return "Decisions chỉ xác nhận là báo cáo, giữ trạng thái agent khai";
  if (update.verification === "unchecked") return "chưa kiểm bằng Decisions";
  return null;
}

interface TaskProgressBlockProps {
  items: TaskProgressOut[];
  topicIndexById: Record<string, number>;
  selectedPointKey: string | null;
  onSelectPoint: (key: string, evidenceIds: string[]) => void;
}

// Tab "Tiến độ" của v3: mỗi việc trong danh sách việc cần báo cáo một thẻ, kèm các cập nhật
// (bấm để tô lượt nói làm bằng chứng). Trạng thái lấy theo cập nhật thắng ở backend: lượt chỉ
// đạo/kết luận thắng lượt báo cáo, cùng loại thì lượt muộn hơn thắng.
export function TaskProgressBlock({ items, topicIndexById, selectedPointKey, onSelectPoint }: TaskProgressBlockProps) {
  if (items.length === 0) return <EmptyState>Request không có danh sách việc cần báo cáo.</EmptyState>;

  const counts = items.reduce<Record<string, number>>((acc, item) => {
    acc[item.status] = (acc[item.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-[12.5px] text-neutral-700">
        {Object.entries(counts)
          .map(([status, count]) => `${count} ${statusLabel(status).toLowerCase()}`)
          .join(" · ")}
      </p>
      {items.map((progress) => (
        <section key={progress.task_id} className="bg-surface">
          <header className="flex flex-wrap items-start gap-3 border-b border-divider px-4 py-3">
            <span className="flex-none bg-neutral-200 px-1.5 py-0.5 font-mono text-[12px]">{progress.task_id}</span>
            <div className="min-w-0 flex-1">
              <div className="font-heading text-[15px] leading-snug font-extrabold">{progress.title}</div>
              <div className="mt-0.5 text-[11.5px] text-neutral-700">
                Chủ trì: {progress.owner} · Hạn: {deadlineText(progress)}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {progress.previous_status && (
                <span className="text-[11.5px] text-neutral-600">{statusLabel(progress.previous_status)} →</span>
              )}
              <span className={STATUS_CLASS[progress.status] ?? "tag tag-neutral"}>{statusLabel(progress.status)}</span>
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
            <p className="m-0 px-4 py-3 text-[12.5px] text-neutral-600">Không chủ đề nào nói tới việc này.</p>
          ) : (
            <div className="p-1.5">
              {progress.deciding_update && (progress.deciding_update.directive || progress.deciding_update.blockers.length > 0) && (
                <div className="px-3 pt-1.5 pb-2 text-[12.5px] leading-snug">
                  {progress.deciding_update.directive && (
                    <div>
                      <span className="text-neutral-600">Chỉ đạo: </span>
                      {progress.deciding_update.directive}
                    </div>
                  )}
                  {progress.deciding_update.blockers.length > 0 && (
                    <div>
                      <span className="text-neutral-600">Vướng mắc: </span>
                      {progress.deciding_update.blockers.join("; ")}
                    </div>
                  )}
                </div>
              )}
              <div className="px-3 pt-1">
                <SectionLabel>Cập nhật theo chủ đề</SectionLabel>
              </div>
              <ol className="m-0 list-none p-0">
                {progress.updates.map((update, idx) => {
                  const key = `progress:${progress.task_id}:${idx}`;
                  const topicIndex = topicIndexById[update.segment_id];
                  const note = updateNote(update);
                  const deciding = progress.deciding_update && update.status_turn_id === progress.deciding_update.status_turn_id
                    && update.segment_id === progress.deciding_update.segment_id;
                  return (
                    <li key={key}>
                      <EvidenceItem
                        selected={key === selectedPointKey}
                        onSelect={() => onSelectPoint(key, update.evidence_ids)}
                        quotes={update.quotes}
                        meta={
                          <>
                            <span className={STATUS_CLASS[update.status] ?? "tag tag-neutral"}>{statusLabel(update.status)}</span>
                            {deciding && progress.updates.length > 1 && <span className="tag tag-ok">quyết định trạng thái</span>}
                            {update.p_directive !== null && update.p_directive >= 0.8 && (
                              <span className="tag tag-outline" title={`p = ${update.p_directive.toFixed(2)}`}>
                                lượt chỉ đạo
                              </span>
                            )}
                            {topicIndex !== undefined && (
                              <span className="tag tag-muted">Chủ đề {String(topicIndex + 1).padStart(2, "0")}</span>
                            )}
                            {update.status_turn_id && <span className="tag tag-muted">{update.status_turn_id}</span>}
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
      ))}
    </div>
  );
}
