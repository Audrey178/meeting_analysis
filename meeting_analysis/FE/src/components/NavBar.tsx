import type { AnalysisStatus } from "../hooks/useAnalysis";

const STATUS_LABEL: Record<AnalysisStatus, string> = {
  idle: "chưa phân tích",
  running: "đang chạy",
  success: "hoàn tất",
  error: "lỗi",
};

interface NavBarProps {
  status: AnalysisStatus;
  meetingId?: string;
  revisionId?: string;
  /** Short pipeline name shown next to the meeting id. */
  pipelineLabel?: string;
  apiHealthy: boolean | null;
  onReset: () => void;
}

const STATUS_STYLE: Record<AnalysisStatus, { pill: string; dot: string }> = {
  idle: { pill: "bg-neutral-200 text-neutral-800", dot: "bg-neutral-500" },
  running: { pill: "bg-neutral-200 text-neutral-800", dot: "bg-accent animate-pulse" },
  success: { pill: "bg-ok-100 text-ok-800", dot: "bg-ok" },
  error: { pill: "bg-accent-100 text-accent-800", dot: "bg-accent" },
};

export function NavBar({ status, meetingId, revisionId, pipelineLabel, apiHealthy, onReset }: NavBarProps) {
  const style = STATUS_STYLE[status];

  return (
    <div className="flex items-center gap-4 border-b-2 border-divider px-5 py-2.5">
      <span className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center bg-accent font-heading text-[12px] font-extrabold text-bg">
          M
        </span>
        <span className="font-heading text-[16px] font-extrabold">Meeting Analysis</span>
      </span>
      {meetingId && status !== "idle" && (
        <span className="flex min-w-0 items-center gap-2 border-l border-divider pl-4 text-[13px]">
          <span className="truncate font-semibold">{meetingId}</span>
          {revisionId && <span className="text-neutral-600">{revisionId}</span>}
          {pipelineLabel && <span className="tag tag-muted !py-0">{pipelineLabel}</span>}
        </span>
      )}
      <span className={`ml-auto flex items-center gap-1.5 px-2.5 py-1 font-heading text-[11.5px] font-extrabold ${style.pill}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
        {STATUS_LABEL[status]}
      </span>
      <span
        className="flex items-center gap-1.5 text-[11.5px] text-neutral-700"
        title="GET /health"
      >
        <span
          className={`h-2 w-2 rounded-full ${
            apiHealthy === null ? "bg-neutral-400" : apiHealthy ? "bg-ok" : "bg-accent"
          }`}
        />
        {apiHealthy === null ? "đang kiểm tra API…" : apiHealthy ? "API online" : "API offline"}
      </span>
      {status !== "idle" && (
        <button type="button" className="btn btn-secondary !py-1.5 !text-[13px]" onClick={onReset}>
          ← Cuộc họp khác
        </button>
      )}
    </div>
  );
}
