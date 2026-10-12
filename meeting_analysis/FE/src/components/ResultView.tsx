import { type ReactNode, useMemo, useState } from "react";
import type { AnalyzeV3Result } from "../api/types";
import { formatDurationMs, groupActionItemsByAssignee } from "../lib/format";
import { DecisionBlock } from "./DecisionBlock";
import { TaskAssignmentBlock } from "./TaskAssignmentBlock";
import { TopicBlock } from "./TopicBlock";
import { EmptyState } from "./agentic/primitives";

export type ResultTab = "topics" | "assignments" | "conclusion" | "extra" | "verification" | "raw";

/** Tab thêm sau "Kết luận" ("Tiến độ" khi request có danh sách việc). */
export interface ExtraTab {
  label: string;
  render: (ctx: { topicIndexById: Record<string, number> }) => ReactNode;
}

/** Nội dung tab "Kiểm chứng" (bản ghi Verifier). */
export interface VerificationTab {
  /** Số mục bị nghi ngờ (nhãn tab). */
  count: number;
  /** Số mục được giữ lại (ô thống kê). */
  kept: number;
  statLabel: string;
  render: (ctx: { topicIndexById: Record<string, number> }) => ReactNode;
}

interface ResultViewProps {
  data: AnalyzeV3Result;
  verification: VerificationTab;
  extraTab?: ExtraTab;
  /** Dòng ghi chú thêm dưới thanh tab (vd. agent bị Planner bỏ qua). */
  notice?: ReactNode;
  /** Thanh điều khiển đầu nội dung từng tab (nút chạy lại phần đó + trạng thái cache). */
  tabToolbars?: Partial<Record<ResultTab, ReactNode>>;
  /** Tab có phần đang chạy lại (nhãn tab thêm dấu "…"). */
  busyTabs?: Partial<Record<ResultTab, boolean>>;
  /** Nút đặt cạnh thời gian chạy ở hàng thống kê (chạy lại toàn bộ). */
  headerAction?: ReactNode;
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

function StatTile({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="flex min-w-[112px] flex-col gap-0.5 px-4 py-3">
      <span className="font-heading text-[26px] leading-none font-extrabold">{value}</span>
      <span className="text-[11.5px] text-neutral-700">{label}</span>
    </div>
  );
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function RawJsonView({ data }: { data: AnalyzeV3Result }) {
  const json = useMemo(() => JSON.stringify(data, null, 2), [data]);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={handleCopy}
        title={copied ? "Đã sao chép" : "Sao chép JSON"}
        aria-label="Sao chép JSON"
        className="absolute top-2 right-2 flex items-center gap-1.5 rounded bg-neutral-700 px-2 py-1 text-[11.5px] text-neutral-100 hover:bg-neutral-600"
      >
        {copied ? <CheckIcon /> : <CopyIcon />}
        {copied ? "Đã sao chép" : "Sao chép"}
      </button>
      <pre className="overflow-x-auto bg-neutral-900 p-4 pr-28 text-[12px] leading-relaxed text-neutral-100">{json}</pre>
    </div>
  );
}

export function ResultView({
  data,
  verification,
  extraTab,
  notice,
  tabToolbars,
  busyTabs,
  headerAction,
  elapsedMs,
  selectedPointKey,
  onSelectPoint,
  initialTab = "topics",
}: ResultViewProps) {
  const [tab, setTab] = useState<ResultTab>(initialTab);

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

  const tabs: [ResultTab, string][] = [
    ["topics", `Diễn biến (${data.topics.length})`],
    ["assignments", `Giao việc (${data.verified_assignments.length})`],
    ["conclusion", `Kết luận (${data.verified_decisions.length})`],
    ...(extraTab ? [["extra", extraTab.label] as [ResultTab, string]] : []),
    ["verification", `Kiểm chứng (${verification.count})`],
    ["raw", "Raw JSON"],
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-stretch divide-x divide-divider border-b-2 border-divider">
        <StatTile value={data.topics.length} label="chủ đề" />
        <StatTile value={pointCount} label="luận điểm" />
        <StatTile value={data.verified_assignments.length} label={`việc giao · ${people} người`} />
        <StatTile value={data.verified_decisions.length} label="kết luận" />
        <StatTile
          value={verification.count ? `${verification.kept}/${verification.count}` : "—"}
          label={verification.statLabel}
        />
        <div className="ml-auto flex items-center gap-3 px-4 text-xs text-neutral-700">
          {headerAction}
          {formatDurationMs(elapsedMs)}
        </div>
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
            {busyTabs?.[value] ? `${label} …` : label}
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
        {tabToolbars?.[tab]}

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

        {tab === "extra" && extraTab && extraTab.render({ topicIndexById })}

        {tab === "verification" && verification.render({ topicIndexById })}

        {tab === "raw" && <RawJsonView data={data} />}
      </div>
    </div>
  );
}
