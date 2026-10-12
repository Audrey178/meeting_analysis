import type { ReactNode } from "react";
import type { AnalyzeV3Result, V3Part, V3PartMeta } from "../../api/types";
import { ResultView, type ResultTab } from "../ResultView";
import { TaskProgressBlock } from "./TaskProgressBlock";
import { VerifierRecordsBlock } from "./VerifierRecordsBlock";

interface V3ResultViewProps {
  data: AnalyzeV3Result;
  elapsedMs: number;
  selectedPointKey: string | null;
  onSelectPoint: (key: string, evidenceIds: string[]) => void;
  /** Các phần đang chạy lại. */
  reloading: Partial<Record<V3Part, boolean>>;
  /** Lỗi của lần chạy lại gần nhất theo phần (kết quả cũ được giữ). */
  partErrors: Partial<Record<V3Part, string>>;
  onReloadPart: (part: V3Part) => void;
  onRefreshAll: () => void;
}

const AGENT_LABEL: Record<string, string> = { action_agent: "Giao việc", decision_agent: "Kết luận" };

/** Tab hiển thị từng phần (Tiến độ là tab thêm của ResultView). */
const PART_TAB: Record<V3Part, ResultTab> = {
  development: "topics",
  assignments: "assignments",
  decisions: "conclusion",
  progress: "extra",
};

const PART_LABEL: Record<V3Part, string> = {
  development: "Diễn biến",
  assignments: "Giao việc",
  decisions: "Kết luận",
  progress: "Tiến độ",
};

const PARTS = Object.keys(PART_TAB) as V3Part[];

function describePart(meta: V3PartMeta): string {
  const time = new Date(meta.computed_at).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
  return `Lần tính #${meta.generation} · ${time}${meta.from_cache ? " · lấy từ cache" : ""}`;
}

interface PartToolbarProps {
  part: V3Part;
  meta: V3PartMeta;
  busy: boolean;
  error?: string;
  onReload: () => void;
}

function PartToolbar({ part, meta, busy, error, onReload }: PartToolbarProps) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-divider pb-3 text-[12px] text-neutral-700">
      <button
        type="button"
        className="btn btn-secondary px-3 py-1 text-[12.5px]"
        disabled={busy}
        onClick={onReload}
        title={`Tính lại riêng phần ${PART_LABEL[part]} trên cùng chủ đề; các phần khác giữ nguyên`}
      >
        {busy ? `Đang chạy lại ${PART_LABEL[part]}…` : `Chạy lại ${PART_LABEL[part]}`}
      </button>
      <span>{describePart(meta)}</span>
      {meta.status === "incomplete" && <span className="text-accent-800">Có chủ đề lỗi -- nên chạy lại phần này.</span>}
      {error && <span className="break-words text-accent-800">Chạy lại lỗi: {error}</span>}
    </div>
  );
}

// Kết quả v3 hiển thị bằng ResultView: tab Kiểm chứng là bản ghi Verifier, thêm tab Tiến độ
// khi request có danh sách việc cần báo cáo, và ghi chú các agent bị Planner bỏ qua. Mỗi tab
// của một phần có nút chạy lại riêng phần đó.
export function V3ResultView({
  data,
  elapsedMs,
  selectedPointKey,
  onSelectPoint,
  reloading,
  partErrors,
  onReloadPart,
  onRefreshAll,
}: V3ResultViewProps) {
  const records = data.verification_records;
  const kept = records.filter((record) => record.verdict === "keep" || record.verdict === "revise" || record.verdict === "unresolved").length;
  const skipped = data.skipped_agents ?? [];
  const progress = data.task_progress ?? [];

  const tabToolbars: Partial<Record<ResultTab, ReactNode>> = {};
  const busyTabs: Partial<Record<ResultTab, boolean>> = {};
  for (const part of PARTS) {
    const meta = data.parts?.[part];
    if (!meta) continue;
    busyTabs[PART_TAB[part]] = Boolean(reloading[part]);
    tabToolbars[PART_TAB[part]] = (
      <PartToolbar
        part={part}
        meta={meta}
        busy={Boolean(reloading[part])}
        error={partErrors[part]}
        onReload={() => onReloadPart(part)}
      />
    );
  }
  const anyReloading = PARTS.some((part) => reloading[part]);

  const notice =
    skipped.length > 0 ? (
      <>
        Planner bỏ qua {skipped.length} lời gọi agent ở chủ đề không có lượt giao/chốt việc:{" "}
        {skipped.map((item) => `${item.segment_id} (${AGENT_LABEL[item.agent] ?? item.agent})`).join(", ")}.
      </>
    ) : null;

  return (
    <ResultView
      data={data}
      elapsedMs={elapsedMs}
      selectedPointKey={selectedPointKey}
      onSelectPoint={onSelectPoint}
      notice={notice}
      tabToolbars={tabToolbars}
      busyTabs={busyTabs}
      headerAction={
        <button
          type="button"
          className="btn btn-ghost px-2 py-1 text-[12px]"
          disabled={anyReloading}
          onClick={onRefreshAll}
          title="Cắt chủ đề, gán nhãn và tính lại mọi phần, bỏ qua cache (gọi LLM thật)"
        >
          Chạy lại toàn bộ
        </button>
      }
      extraTab={
        progress.length > 0
          ? {
              label: `Tiến độ (${progress.length})`,
              render: ({ topicIndexById }) => (
                <TaskProgressBlock
                  items={progress}
                  topicIndexById={topicIndexById}
                  selectedPointKey={selectedPointKey}
                  onSelectPoint={onSelectPoint}
                />
              ),
            }
          : undefined
      }
      verification={{
        count: records.length,
        kept,
        statLabel: "giữ sau Verifier",
        render: ({ topicIndexById }) => (
          <VerifierRecordsBlock
            records={records}
            topicIndexById={topicIndexById}
            selectedPointKey={selectedPointKey}
            onSelectPoint={onSelectPoint}
          />
        ),
      }}
    />
  );
}
