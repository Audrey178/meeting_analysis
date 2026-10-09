import type { ActionItemOut, ActionItemV3Out, ActorAssigneeOut, ActorType, AssigneeRole } from "../api/types";
import { groupActionItemsByAssignee, initialsOf, speakerColor, UNASSIGNED_LABEL } from "../lib/format";
import { Avatar, CitationCount, EmptyState, EvidenceItem, VerificationTag } from "./agentic/primitives";

const DEADLINE_KIND_PREFIX: Partial<Record<NonNullable<ActionItemOut["deadline_kind"]>, string>> = {
  before: "trước ",
  end_of_period: "cuối kỳ · ",
};

/** "trước 15/11/2026" when the deadline resolved to a date; otherwise the raw phrase. */
function formatDeadline(item: ActionItemOut): string {
  if (!item.deadline_date) return item.deadline_raw ?? "";
  const [year, month, day] = item.deadline_date.split("-");
  const prefix = (item.deadline_kind && DEADLINE_KIND_PREFIX[item.deadline_kind]) ?? "";
  return `${prefix}${day}/${month}/${year}`;
}

const ROLE_LABEL: Record<AssigneeRole, string> = { lead: "Chủ trì", support: "Phối hợp", joint: "Cùng thực hiện" };
const ACTOR_TYPE_LABEL: Partial<Record<ActorType, string>> = { person: "Cá nhân", organization: "Đơn vị" };

/** Other parties of the same task, e.g. "cùng Sở Xây dựng (phối hợp)". */
function OtherAssignees({ item, current }: { item: ActionItemV3Out; current: string }) {
  const others = (item.assignees ?? []).filter((assignee) => (assignee.name ?? assignee.mention) !== current);
  if (others.length === 0) return null;
  const text = others
    .map((assignee) => `${assignee.name ?? `${assignee.mention} (chưa rõ)`} · ${ROLE_LABEL[assignee.role].toLowerCase()}`)
    .join("; ");
  return <span className="tag tag-muted max-w-[320px] truncate" title={text}>cùng: {text}</span>;
}

/** How the current party was identified when the transcript called it something else,
 * e.g. "Đảng ủy ban" -> "Đảng ủy UBND Thành phố"; the tooltip carries the resolver's or
 * the Verifier's reason (which of two people named Sơn, and why). */
function ResolvedFrom({ item, current }: { item: ActionItemV3Out; current: string }) {
  const assignee = (item.assignees ?? []).find((candidate) => candidate.name === current);
  if (!assignee) return null;
  const sameText = assignee.mention.trim().toLocaleLowerCase("vi") === current.trim().toLocaleLowerCase("vi");
  if (sameText && assignee.candidates.length < 2) return null;
  return (
    <span className="tag tag-outline max-w-[280px] truncate" title={assignee.reason || undefined}>
      {sameText ? "đã chọn giữa nhiều ứng viên" : `từ “${assignee.mention}”`}
    </span>
  );
}

/** Unresolved parties of a task with their scored candidates, so the reader can pick. */
function UnresolvedCandidates({ assignees }: { assignees: ActorAssigneeOut[] }) {
  const unresolved = assignees.filter((assignee) => !assignee.name);
  if (unresolved.length === 0) return null;
  return (
    <>
      {unresolved.map((assignee) => (
        <span key={assignee.mention} className="tag tag-accent" title={assignee.reason}>
          “{assignee.mention}”:{" "}
          {assignee.candidates.length > 0
            ? assignee.candidates.map((c) => `${c.name} ${c.score.toFixed(2)}`).join(" · ")
            : "không có ứng viên"}
        </span>
      ))}
    </>
  );
}

interface TaskAssignmentBlockProps {
  items: ActionItemOut[];
  topicIndexById: Record<string, number>;
  topicTitleById: Record<string, string>;
  selectedPointKey: string | null;
  onSelectPoint: (key: string, evidenceIds: string[]) => void;
}

export function TaskAssignmentBlock({
  items,
  topicIndexById,
  topicTitleById,
  selectedPointKey,
  onSelectPoint,
}: TaskAssignmentBlockProps) {
  const groups = groupActionItemsByAssignee(items);

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
              <Avatar label={unassigned ? "?" : initialsOf(group.assignee)} color={speakerColor(group.assignee)} muted={unassigned} />
              <div className="min-w-0 flex-1">
                <div className="font-heading text-[15px] font-extrabold">{group.assignee}</div>
                <div className="text-[11.5px] text-neutral-700">{group.entries.length} việc</div>
              </div>
              {group.actorType && ACTOR_TYPE_LABEL[group.actorType] && (
                <span className="tag tag-neutral">{ACTOR_TYPE_LABEL[group.actorType]}</span>
              )}
            </header>
            <ol className="m-0 list-none p-1.5">
              {group.entries.map(({ item, role }, itemIdx) => {
                const key = `assignment:${groupIdx}:${itemIdx}`;
                const topicIndex = topicIndexById[item.segment_id];
                return (
                  <li key={key}>
                    <EvidenceItem
                      selected={key === selectedPointKey}
                      onSelect={() => onSelectPoint(key, item.evidence_ids)}
                      quotes={item.quotes}
                      leading={
                        <span className="w-5 flex-none pt-px text-right font-mono text-[12px] text-neutral-500">
                          {itemIdx + 1}.
                        </span>
                      }
                      trailing={<CitationCount count={item.citation_count} />}
                      meta={
                        <>
                          {item.deadline_raw && (
                            <span className="tag tag-outline" title={item.deadline_raw}>
                              Hạn: {formatDeadline(item)}
                            </span>
                          )}
                          {topicIndex !== undefined && (
                            <span
                              className="tag tag-muted max-w-[280px] truncate"
                              title={topicTitleById[item.segment_id]}
                            >
                              Chủ đề {String(topicIndex + 1).padStart(2, "0")}
                            </span>
                          )}
                          {role && (item.assignees?.length ?? 0) > 1 && (
                            <span className={role === "lead" ? "tag tag-ok" : "tag tag-outline"}>{ROLE_LABEL[role]}</span>
                          )}
                          {!unassigned && <ResolvedFrom item={item} current={group.assignee} />}
                          {!unassigned && <OtherAssignees item={item} current={group.assignee} />}
                          {unassigned && <UnresolvedCandidates assignees={item.assignees ?? []} />}
                          <VerificationTag verification={item.verification} />
                        </>
                      }
                    >
                      {item.text}
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
