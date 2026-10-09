import { type ReactNode, useMemo, useState } from "react";
import type { AnalyzeResponse } from "../api/types";
import { formatDurationMs, groupActionItemsByAssignee } from "../lib/format";
import { DecisionBlock } from "./DecisionBlock";
import { TaskAssignmentBlock } from "./TaskAssignmentBlock";
import { TopicBlock } from "./TopicBlock";
import { VerificationBlock } from "./VerificationBlock";
import { EmptyState } from "./agentic/primitives";

export type ResultTab = "topics" | "assignments" | "conclusion" | "verification" | "raw";

/** Thay tab "Kiểm chứng" mặc định (Debate+Judge của v1) bằng nội dung khác -- v3 dùng Verifier. */
export interface VerificationOverride {
  /** Số mục bị nghi ngờ (nhãn tab). */
  count: number;
  /** Số mục được giữ lại (ô thống kê). */
  kept: number;
  statLabel: string;
  render: (ctx: { topicIndexById: Record<string, number> }) => ReactNode;
}

interface ResultViewProps {
  data: AnalyzeResponse;
  verification?: VerificationOverride;
  /** Dòng ghi chú thêm dưới thanh tab (vd. agent bị Planner bỏ qua ở v3). */
  notice?: ReactNode;
  elapsedMs: number;
  selectedPointKey: string | null;
  onSelectPoint: (key: string, evidenceIds: string[]) => void;
  initialTab?: ResultTab;
}

function countBySegment(items: { segment_id: string }[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) counts[item.segment_id] = (counts[item.segment_id] ?? 0) + 1;
  return counts;
}

function StatTile({ value, label, hint }: { value: number | string; label: string; hint?: string }) {
  return (
    <div className="flex min-w-[112px] flex-col gap-0.5 px-4 py-3" title={hint}>
      <span className="font-heading text-[26px] leading-none font-extrabold">{value}</span>
      <span className="text-[11.5px] text-neutral-700">{label}</span>
    </div>
  );
}

export function ResultView({
  data,
  verification,
  notice,
  elapsedMs,
  selectedPointKey,
  onSelectPoint,
  initialTab = "topics",
}: ResultViewProps) {
  const [tab, setTab] = useState<ResultTab>(initialTab);
  const debates = data.debate_records ?? [];

  const { topicIndexById, topicTitleById } = useMemo(
    () => ({
      topicIndexById: Object.fromEntries(data.topics.map((topic, idx) => [topic.segment_id, idx])),
      topicTitleById: Object.fromEntries(data.topics.map((topic) => [topic.segment_id, topic.title])),
    }),
    [data.topics],
  );
  const assignmentsBySegment = useMemo(() => countBySegment(data.verified_assignments), [data.verified_assignments]);
  const decisionsBySegment = useMemo(() => countBySegment(data.verified_decisions), [data.verified_decisions]);

  const pointCount = data.topics.reduce(
    (sum, topic) => sum + topic.speakers.reduce((inner, speaker) => inner + speaker.points.length, 0),
    0,
  );
  const people = groupActionItemsByAssignee(data.verified_assignments).length;
  const dropped = debates.filter((record) => (record.verdict ?? (record.kept ? "keep" : "drop")) === "drop").length;

  const tabs: [ResultTab, string][] = [
    ["topics", `Diễn biến (${data.topics.length})`],
    ["assignments", `Giao việc (${data.verified_assignments.length})`],
    ["conclusion", `Kết luận (${data.verified_decisions.length})`],
    ["verification", `Kiểm chứng (${verification ? verification.count : debates.length})`],
    ["raw", "Raw JSON"],
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-stretch divide-x divide-divider border-b-2 border-divider">
        <StatTile value={data.topics.length} label="chủ đề" />
        <StatTile value={pointCount} label="luận điểm" />
        <StatTile value={data.verified_assignments.length} label={`việc giao · ${people} người`} />
        <StatTile value={data.verified_decisions.length} label="kết luận" />
        {verification ? (
          <StatTile
            value={verification.count ? `${verification.kept}/${verification.count}` : "—"}
            label={verification.statLabel}
          />
        ) : (
          <StatTile
            value={debates.length ? `${debates.length - dropped}/${debates.length}` : "—"}
            label="giữ sau tranh luận"
            hint="Số mục bị nghi ngờ được giữ lại / tổng số mục phải qua Debate+Judge"
          />
        )}
        <div className="ml-auto flex items-center px-4 text-xs text-neutral-700">{formatDurationMs(elapsedMs)}</div>
      </div>

      <div className="flex overflow-x-auto border-b-2 border-divider">
        {tabs.map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={`px-4 py-2.5 font-heading text-[12.5px] font-extrabold whitespace-nowrap ${
              tab === value ? "bg-accent text-bg" : "text-neutral-700 hover:bg-neutral-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {data.failed_topics && data.failed_topics.length > 0 && (
        <div className="border-b border-divider bg-accent-100 px-8 py-2 text-[12.5px] text-accent-800">
          {data.failed_topics.length} lời gọi agent vẫn lỗi sau khi thử lại -- kết quả của chủ đề tương ứng có thể thiếu
          ({data.failed_topics.map((failure) => `${failure.segment_id}/${failure.agent}`).join(", ")}).
        </div>
      )}

      {notice && (
        <div className="border-b border-divider bg-surface px-8 py-2 text-[12.5px] text-neutral-700">{notice}</div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
        {tab !== "raw" && (
          <p className="mb-4 text-[12px] text-neutral-600">
            Bấm vào một mục để tô các lượt nói làm bằng chứng trên transcript và xem trích dẫn.
          </p>
        )}

        {tab === "topics" &&
          (data.topics.length === 0 ? (
            <EmptyState>Không có chủ đề nào được trích ra.</EmptyState>
          ) : (
            data.topics.map((topic, idx) => (
              <TopicBlock
                key={topic.segment_id}
                topic={topic}
                index={idx}
                assignmentCount={assignmentsBySegment[topic.segment_id] ?? 0}
                decisionCount={decisionsBySegment[topic.segment_id] ?? 0}
                selectedPointKey={selectedPointKey}
                onSelectPoint={onSelectPoint}
              />
            ))
          ))}

        {tab === "assignments" && (
          <TaskAssignmentBlock
            items={data.verified_assignments}
            topicIndexById={topicIndexById}
            topicTitleById={topicTitleById}
            selectedPointKey={selectedPointKey}
            onSelectPoint={onSelectPoint}
          />
        )}

        {tab === "conclusion" && (
          <DecisionBlock
            decisions={data.verified_decisions}
            topics={data.topics}
            selectedPointKey={selectedPointKey}
            onSelectPoint={onSelectPoint}
          />
        )}

        {tab === "verification" && verification && verification.render({ topicIndexById })}

        {tab === "verification" && !verification && (
          <VerificationBlock
            records={debates}
            topicIndexById={topicIndexById}
            selectedPointKey={selectedPointKey}
            onSelectPoint={onSelectPoint}
          />
        )}

        {tab === "raw" && (
          <pre className="overflow-x-auto bg-neutral-900 p-4 text-[12px] leading-relaxed text-neutral-100">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
