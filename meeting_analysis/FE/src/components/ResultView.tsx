import { type ReactNode, useMemo, useState } from "react";
import type { Citation, DocumentKind, MeetingDocument, VerificationRecordOut } from "../api/types";
import type { DocumentSlot, DocumentSlots } from "../hooks/useMeetingDocuments";
import type { TranscriptIndex } from "../lib/citations";
import { formatDurationMs, groupTasksByAssignee, UNASSIGNED_LABEL } from "../lib/format";
import { DecisionBlock } from "./DecisionBlock";
import { TaskAssignmentBlock } from "./TaskAssignmentBlock";
import { TopicBlock } from "./TopicBlock";
import { EmptyState } from "./agentic/primitives";
import { TaskProgressBlock } from "./v3/TaskProgressBlock";
import { VerifierRecordsBlock } from "./v3/VerifierRecordsBlock";

type ResultTab = "topics" | "assignments" | "progress" | "conclusion" | "verification" | "raw";

/** Document hiển thị trong từng tab (Kiểm chứng gom bản ghi của Giao việc và Kết luận). */
const TAB_DOCUMENT: Partial<Record<ResultTab, DocumentKind>> = {
  topics: "content",
  assignments: "tasks",
  progress: "tasks",
  conclusion: "decisions",
};

const DOCUMENT_LABEL: Record<DocumentKind, string> = { content: "Diễn biến", tasks: "Giao việc", decisions: "Kết luận" };
const AGENT_LABEL: Record<string, string> = {
  content_agent: "Diễn biến",
  action_agent: "Giao việc",
  decision_agent: "Kết luận",
  progress_agent: "Tiến độ",
};

interface ResultViewProps {
  docs: DocumentSlots;
  transcript: TranscriptIndex;
  elapsedMs: number;
  selectedKey: string | null;
  onSelect: (key: string, citation: Citation) => void;
  onReload: (kind: DocumentKind) => void;
  onRefreshAll: () => void;
}

function StatTile({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="flex min-w-[112px] flex-col gap-0.5 px-4 py-3">
      <span className="font-heading text-[26px] leading-none font-extrabold">{value}</span>
      <span className="text-[11.5px] text-neutral-700">{label}</span>
    </div>
  );
}

function describe(doc: MeetingDocument): string {
  const time = new Date(doc.generation.generated_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
  const { processed_segment_count: processed, total_segment_count: total } = doc.generation.coverage;
  return `Lần tính #${doc.artifact_revision} · ${time} · phủ ${processed}/${total} dòng`;
}

/** Thanh đầu tab: nút tính lại document, lần tính, cảnh báo chủ đề lỗi, lỗi lần tính lại gần nhất. */
function DocumentToolbar({
  kind,
  slot,
  onReload,
}: {
  kind: DocumentKind;
  slot: DocumentSlot<DocumentKind>;
  onReload: () => void;
}) {
  const label = DOCUMENT_LABEL[kind];
  const doc = slot.data;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-divider pb-3 text-[12px] text-neutral-700">
      <button
        type="button"
        className="btn btn-secondary px-3 py-1 text-[12.5px]"
        disabled={slot.loading}
        onClick={onReload}
        title={`Tính lại riêng ${label} trên cùng chủ đề; các phần khác giữ nguyên`}
      >
        {slot.loading ? `Đang tính ${label}…` : doc ? `Chạy lại ${label}` : `Thử lại ${label}`}
      </button>
      {doc && <span>{describe(doc)}</span>}
      {doc?.generation.status === "partial" && (
        <span className="text-accent-800">
          Lỗi ở {doc.generation.warnings.length} chủ đề (
          {doc.generation.warnings.map((warning) => `${warning.topic_id}/${AGENT_LABEL[warning.agent] ?? warning.agent}`).join(", ")}
          ) -- nên chạy lại.
        </span>
      )}
      {slot.error && <span className="break-words text-accent-800">Lỗi: {slot.error}</span>}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <button
      type="button"
      onClick={handleCopy}
      className="absolute top-2 right-2 rounded bg-neutral-700 px-2 py-1 text-[11.5px] text-neutral-100 hover:bg-neutral-600"
    >
      {copied ? "Đã sao chép" : "Sao chép"}
    </button>
  );
}

function RawJsonView({ docs }: { docs: DocumentSlots }) {
  const available = (Object.keys(DOCUMENT_LABEL) as DocumentKind[]).filter((kind) => docs[kind].data);
  const [kind, setKind] = useState<DocumentKind>(available[0] ?? "content");
  const json = useMemo(() => JSON.stringify(docs[kind].data, null, 2), [docs, kind]);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-1.5">
        {available.map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setKind(value)}
            className={`btn px-3 py-1 text-[12px] ${kind === value ? "btn-primary" : "btn-secondary"}`}
          >
            {docs[value].data!.document_type}
          </button>
        ))}
      </div>
      <div className="relative">
        <CopyButton text={json} />
        <pre className="overflow-x-auto bg-neutral-900 p-4 pr-28 text-[12px] leading-relaxed text-neutral-100">{json}</pre>
      </div>
    </div>
  );
}

function countBy<T>(items: T[], keyOf: (item: T) => string | null): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) {
    const key = keyOf(item);
    if (key) counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}

// Kết quả phân tích: ba document hiển thị qua các tab; document nào về trước hiện trước, mỗi
// tab có nút tính lại riêng document của nó.
export function ResultView({ docs, transcript, elapsedMs, selectedKey, onSelect, onReload, onRefreshAll }: ResultViewProps) {
  const [tab, setTab] = useState<ResultTab>("topics");
  const content = docs.content.data;
  const tasksDoc = docs.tasks.data;
  const decisionsDoc = docs.decisions.data;

  const topics = useMemo(() => content?.data.topics ?? [], [content]);
  const allTasks = useMemo(() => tasksDoc?.data.tasks ?? [], [tasksDoc]);
  const newTasks = useMemo(() => allTasks.filter((task) => task.extracted.progress === null), [allTasks]);
  const backlog = useMemo(() => allTasks.filter((task) => task.extracted.progress !== null), [allTasks]);
  const decisions = useMemo(() => decisionsDoc?.data.items ?? [], [decisionsDoc]);
  const records: VerificationRecordOut[] = useMemo(
    () => [
      ...(tasksDoc?.extensions.audit.verification_records ?? []),
      ...(decisionsDoc?.extensions.audit.verification_records ?? []),
    ],
    [tasksDoc, decisionsDoc],
  );
  const skipped = [
    ...(tasksDoc?.extensions.audit.skipped_agents ?? []),
    ...(decisionsDoc?.extensions.audit.skipped_agents ?? []),
  ];

  const { topicIndexById, topicTitleById } = useMemo(
    () => ({
      topicIndexById: Object.fromEntries(topics.map((topic, idx) => [topic.topic_id, idx])),
      topicTitleById: Object.fromEntries(topics.map((topic) => [topic.topic_id, topic.extracted.content.title])),
    }),
    [topics],
  );
  const tasksByTopic = useMemo(() => countBy(newTasks, (task) => task.extensions.topic_id), [newTasks]);
  const decisionsByTopic = useMemo(() => countBy(decisions, (item) => item.extensions.topic_id), [decisions]);

  const pointCount = topics.reduce((sum, topic) => sum + topic.extracted.discussion_points.length, 0);
  const parties = groupTasksByAssignee(newTasks).filter((group) => group.assignee !== UNASSIGNED_LABEL).length;
  const kept = records.filter((record) => ["keep", "revise", "unresolved"].includes(record.verdict)).length;
  const anyLoading = (Object.keys(DOCUMENT_LABEL) as DocumentKind[]).some((kind) => docs[kind].loading);

  /** Nhãn tab: số mục khi đã có document, "…" khi đang tính. */
  function tabLabel(label: string, kind: DocumentKind | null, count: number | null): string {
    const slot = kind ? docs[kind] : null;
    const counted = slot && !slot.data ? label : `${label}${count !== null ? ` (${count})` : ""}`;
    return slot?.loading ? `${counted} …` : counted;
  }

  const tabs: [ResultTab, string][] = [
    ["topics", tabLabel("Diễn biến", "content", topics.length)],
    ["assignments", tabLabel("Giao việc", "tasks", newTasks.length)],
    ...(backlog.length > 0 ? [["progress", tabLabel("Tiến độ", "tasks", backlog.length)] as [ResultTab, string]] : []),
    ["conclusion", tabLabel("Kết luận", "decisions", decisions.length)],
    ["verification", tabLabel("Kiểm chứng", null, records.length)],
    ["raw", "JSON"],
  ];
  const activeTab = tab === "progress" && backlog.length === 0 ? "assignments" : tab;
  const tabKind = TAB_DOCUMENT[activeTab];

  /** Nội dung tab của document `kind`: chờ/lỗi khi chưa có document. */
  function documentBody(kind: DocumentKind, render: () => ReactNode): ReactNode {
    const slot = docs[kind];
    if (slot.data) return render();
    if (slot.loading) return <EmptyState>Đang tính {DOCUMENT_LABEL[kind]}…</EmptyState>;
    return <EmptyState>Chưa có kết quả {DOCUMENT_LABEL[kind]}.</EmptyState>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-stretch divide-x divide-divider border-b-2 border-divider">
        <StatTile value={content ? topics.length : "—"} label="chủ đề" />
        <StatTile value={content ? pointCount : "—"} label="ý thảo luận" />
        <StatTile value={tasksDoc ? newTasks.length : "—"} label={`việc giao · ${parties} bên nhận`} />
        <StatTile value={decisionsDoc ? decisions.length : "—"} label="kết luận" />
        <StatTile value={records.length ? `${kept}/${records.length}` : "—"} label="giữ sau Verifier" />
        <div className="ml-auto flex items-center gap-3 px-4 text-xs text-neutral-700">
          <button
            type="button"
            className="btn btn-ghost px-2 py-1 text-[12px]"
            disabled={anyLoading}
            onClick={onRefreshAll}
            title="Cắt chủ đề, gán nhãn và tính lại mọi document, bỏ qua cache (gọi LLM thật)"
          >
            Chạy lại toàn bộ
          </button>
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
              activeTab === value ? "bg-accent text-bg" : "text-neutral-700 hover:bg-neutral-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {skipped.length > 0 && (
        <div className="border-b border-divider bg-surface px-8 py-2 text-[12.5px] text-neutral-700">
          Planner bỏ qua {skipped.length} lời gọi agent ở chủ đề không có lượt giao/chốt việc:{" "}
          {skipped.map((item) => `${item.segment_id} (${AGENT_LABEL[item.agent] ?? item.agent})`).join(", ")}.
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
        {tabKind && <DocumentToolbar kind={tabKind} slot={docs[tabKind]} onReload={() => onReload(tabKind)} />}

        {activeTab !== "raw" && (
          <p className="mb-4 text-[12px] text-neutral-600">
            Bấm vào một mục để tô các dòng transcript làm bằng chứng và xem trích dẫn.
          </p>
        )}

        {activeTab === "topics" &&
          documentBody("content", () =>
            topics.length === 0 ? (
              <EmptyState>Không có chủ đề nào được trích ra.</EmptyState>
            ) : (
              topics.map((topic, idx) => (
                <TopicBlock
                  key={topic.topic_id}
                  topic={topic}
                  index={idx}
                  assignmentCount={tasksByTopic[topic.topic_id] ?? 0}
                  decisionCount={decisionsByTopic[topic.topic_id] ?? 0}
                  transcript={transcript}
                  selectedKey={selectedKey}
                  onSelect={onSelect}
                />
              ))
            ),
          )}

        {activeTab === "assignments" &&
          documentBody("tasks", () => (
            <TaskAssignmentBlock
              tasks={newTasks}
              topicIndexById={topicIndexById}
              topicTitleById={topicTitleById}
              transcript={transcript}
              selectedKey={selectedKey}
              onSelect={onSelect}
            />
          ))}

        {activeTab === "progress" &&
          documentBody("tasks", () => (
            <TaskProgressBlock
              tasks={backlog}
              topicIndexById={topicIndexById}
              transcript={transcript}
              selectedKey={selectedKey}
              onSelect={onSelect}
            />
          ))}

        {activeTab === "conclusion" &&
          documentBody("decisions", () => (
            <DecisionBlock
              header={decisionsDoc!.data.header}
              items={decisions}
              topics={topics}
              transcript={transcript}
              selectedKey={selectedKey}
              onSelect={onSelect}
            />
          ))}

        {activeTab === "verification" && (
          <VerifierRecordsBlock
            records={records}
            topicIndexById={topicIndexById}
            selectedKey={selectedKey}
            onSelect={onSelect}
          />
        )}

        {activeTab === "raw" && <RawJsonView docs={docs} />}
      </div>
    </div>
  );
}
