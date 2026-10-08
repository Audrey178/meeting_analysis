import type { ActionItemOut } from "../api/types";
import { groupActionItemsByActor, initialsOf, speakerColor, UNASSIGNED_LABEL } from "../lib/format";
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
  const groups = groupActionItemsByActor(items);

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
                <div className="text-[11.5px] text-neutral-700">{group.items.length} việc</div>
              </div>
            </header>
            <ol className="m-0 list-none p-1.5">
              {group.items.map((item, itemIdx) => {
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
