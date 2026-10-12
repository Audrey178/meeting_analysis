import type { AssignmentTarget, Citation, TaskOut } from "../api/types";
import { quotesOf, type TranscriptIndex } from "../lib/citations";
import {
  formatDue,
  groupTasksByAssignee,
  initialsOf,
  speakerColor,
  speakerName,
  targetName,
  topicNumber,
  type TargetKind,
  UNASSIGNED_LABEL,
} from "../lib/format";
import { Avatar, CitationCount, EmptyState, EvidenceItem, VerificationTag } from "./agentic/primitives";

const ROLE_LABEL: Record<string, string> = { lead: "Chủ trì", support: "Phối hợp", joint: "Cùng thực hiện" };
const KIND_LABEL: Partial<Record<TargetKind, string>> = { person: "Cá nhân", unit: "Đơn vị" };

/** Gợi ý cần người xem lại (``detection.review_hints``) không trùng với nhãn kiểm chứng/ứng viên. */
const HINT_LABEL: Record<string, { label: string; title: string }> = {
  due_unresolved: { label: "hạn chưa quy ra ngày", title: "Hạn nêu trong cuộc họp chưa quy được về một ngày cụ thể" },
  assignee_missing: { label: "thiếu người nhận", title: "Lời giao việc không nêu ai thực hiện" },
};

/** Quan hệ với danh sách việc cần báo cáo (khi request có `tasks`). */
function RelationTag({ task }: { task: TaskOut }) {
  const relation = task.extensions.relation;
  if (relation === "follow_up") {
    return (
      <span className="tag tag-neutral" title="Tiếp nối/làm lại một việc trong danh sách việc cần báo cáo">
        Tiếp nối · {task.workflow.dependency_task_ids.join(", ")}
      </span>
    );
  }
  if (relation === "new") {
    return (
      <span className="tag tag-muted" title="Không thuộc việc nào trong danh sách việc cần báo cáo">
        Việc mới
      </span>
    );
  }
  return null;
}

/** Các bên khác của cùng việc, vd. "cùng: Sở Xây dựng · phối hợp". */
function OtherAssignees({ task, current }: { task: TaskOut; current: AssignmentTarget | null }) {
  const { primary, collaborators } = task.extracted.assignment;
  const others = [primary, ...collaborators].filter((target): target is AssignmentTarget => !!target && target !== current);
  if (others.length === 0) return null;
  const text = others
    .map((target) => {
      const role = ROLE_LABEL[target.extensions.resolution?.role ?? ""] ?? "";
      return `${targetName(target) ?? "chưa rõ"}${role ? ` · ${role.toLowerCase()}` : ""}`;
    })
    .join("; ");
  return (
    <span className="tag tag-muted max-w-[320px] truncate" title={text}>
      cùng: {text}
    </span>
  );
}

/** Bên nhận việc được quy từ cách gọi khác ("Đảng ủy ban" -> "Đảng ủy UBND Thành phố"); tooltip là lý do. */
function ResolvedFrom({ target }: { target: AssignmentTarget | null }) {
  const resolution = target?.extensions.resolution;
  const name = targetName(target);
  if (!resolution?.mention || !name) return null;
  const sameText = resolution.mention.trim().toLocaleLowerCase("vi") === name.trim().toLocaleLowerCase("vi");
  if (sameText && resolution.candidates.length < 2) return null;
  return (
    <span className="tag tag-outline max-w-[280px] truncate" title={resolution.reason || undefined}>
      {sameText ? "đã chọn giữa nhiều ứng viên" : `từ “${resolution.mention}”`}
    </span>
  );
}

/** Bên chưa định danh được kèm các ứng viên có điểm, để người đọc tự chọn. */
function UnresolvedCandidates({ target }: { target: AssignmentTarget | null }) {
  const resolution = target?.extensions.resolution;
  if (!resolution) return null;
  return (
    <span className="tag tag-accent" title={resolution.reason}>
      “{resolution.mention ?? targetName(target)}”:{" "}
      {resolution.candidates.length > 0
        ? resolution.candidates.map((c) => `${c.name} ${c.score.toFixed(2)}`).join(" · ")
        : "không có ứng viên"}
    </span>
  );
}

interface TaskAssignmentBlockProps {
  tasks: TaskOut[];
  topicIndexById: Record<string, number>;
  topicTitleById: Record<string, string>;
  transcript: TranscriptIndex;
  selectedKey: string | null;
  onSelect: (key: string, citation: Citation) => void;
}

// Tab "Giao việc": việc giao mới trong cuộc họp (việc cũ nằm ở tab Tiến độ), gom theo bên nhận việc.
export function TaskAssignmentBlock({
  tasks,
  topicIndexById,
  topicTitleById,
  transcript,
  selectedKey,
  onSelect,
}: TaskAssignmentBlockProps) {
  const groups = groupTasksByAssignee(tasks);

  if (groups.length === 0) {
    return <EmptyState>Không có việc nào được giao.</EmptyState>;
  }

  return (
    <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
      {groups.map((group, groupIdx) => {
        const unassigned = group.assignee === UNASSIGNED_LABEL;
        return (
          <section key={`${group.assignee}-${groupIdx}`} className="self-start bg-surface">
            <header className="flex items-center gap-3 border-b border-divider px-4 py-3">
              <Avatar
                label={unassigned ? "?" : initialsOf(group.assignee)}
                color={speakerColor(group.assignee)}
                muted={unassigned}
              />
              <div className="min-w-0 flex-1">
                <div className="font-heading text-[15px] font-extrabold">{group.assignee}</div>
                <div className="text-[11.5px] text-neutral-700">{group.entries.length} việc</div>
              </div>
              {group.kind && KIND_LABEL[group.kind] && <span className="tag tag-neutral">{KIND_LABEL[group.kind]}</span>}
            </header>
            <ol className="m-0 list-none p-1.5">
              {group.entries.map(({ task, target, role }, itemIdx) => {
                const key = `tasks:${task.task_id}@${groupIdx}`;
                const { extracted, extensions } = task;
                const topicId = extensions.topic_id ?? "";
                const topicIndex = topicIndexById[topicId];
                const segmentIds = extracted.references.segment_ids;
                const parties = (extracted.assignment.primary ? 1 : 0) + extracted.assignment.collaborators.length;
                return (
                  <li key={key}>
                    <EvidenceItem
                      selected={key === selectedKey}
                      onSelect={() => onSelect(key, { segmentIds, turnIds: extensions.evidence_ids })}
                      quotes={quotesOf(transcript, segmentIds)}
                      leading={
                        <span className="w-5 flex-none pt-px text-right font-mono text-[12px] text-neutral-500">
                          {itemIdx + 1}.
                        </span>
                      }
                      trailing={<CitationCount count={segmentIds.length} />}
                      meta={
                        <>
                          {extracted.due && (
                            <span className="tag tag-outline" title={extracted.due.raw ?? undefined}>
                              Hạn: {formatDue(extracted.due)}
                            </span>
                          )}
                          {topicIndex !== undefined && (
                            <span className="tag tag-muted max-w-[280px] truncate" title={topicTitleById[topicId]}>
                              Chủ đề {topicNumber(topicIndex)}
                            </span>
                          )}
                          {parties > 1 && (
                            <span className={role === "lead" ? "tag tag-ok" : "tag tag-outline"}>
                              {ROLE_LABEL[role] ?? role}
                            </span>
                          )}
                          {!unassigned && <ResolvedFrom target={target} />}
                          {!unassigned && <OtherAssignees task={task} current={target} />}
                          {unassigned && <UnresolvedCandidates target={target} />}
                          <RelationTag task={task} />
                          <VerificationTag verification={extensions.verification} />
                          {extracted.detection.review_hints
                            .filter((hint) => HINT_LABEL[hint])
                            .map((hint) => (
                              <span key={hint} className="tag tag-accent" title={HINT_LABEL[hint].title}>
                                {HINT_LABEL[hint].label}
                              </span>
                            ))}
                          {extensions.assigned_by_speaker && (
                            <span className="tag tag-muted" title={`Lượt giao: ${extensions.confirm_turn_id ?? "?"}`}>
                              giao bởi {speakerName(extensions.assigned_by_speaker)}
                            </span>
                          )}
                        </>
                      }
                    >
                      {extracted.content.title}
                    </EvidenceItem>
                  </li>
                );
              })}
            </ol>
          </section>
        );
      })}
    </div>
  );
}
