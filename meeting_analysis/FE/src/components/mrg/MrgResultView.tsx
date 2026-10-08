import { useMemo, useState } from "react";
import type { MrgResult } from "../../api/types";
import { formatDurationMs } from "../../lib/format";
import type { SelectEvidence } from "../../lib/mrg";
import { MrgAssignments } from "./MrgAssignments";
import { MrgAudit, MrgWarnings } from "./MrgAudit";
import { MrgConclusions } from "./MrgConclusions";
import { MrgThreads } from "./MrgThreads";

type Tab = "giao_viec" | "ket_luan" | "dien_bien" | "thong_bao" | "warnings" | "audit" | "raw";

interface MrgResultViewProps {
  data: MrgResult;
  elapsedMs: number;
  selectedKey: string | null;
  onSelect: SelectEvidence;
}

export function MrgResultView({ data, elapsedMs, selectedKey, onSelect }: MrgResultViewProps) {
  const [tab, setTab] = useState<Tab>("giao_viec");
  const taskCount = data.giao_viec.people.reduce((sum, person) => sum + person.tasks.length, 0);
  const issueCount =
    data.ket_luan.resolved.length + data.ket_luan.resolved_conditional.length + data.ket_luan.deferred.length +
    data.ket_luan.open.length;
  const taskLabels = useMemo(() => {
    const labels: Record<string, string> = {};
    for (const person of data.giao_viec.people) for (const task of person.tasks) labels[task.task_id] = task.task;
    for (const item of [...data.giao_viec.warnings, ...data.giao_viec.notes]) labels[item.task_id] = item.task;
    return labels;
  }, [data]);
  const summaries = useMemo(
    () => Object.fromEntries(data.segments.map((segment) => [segment.segment_id, segment.summary])),
    [data],
  );

  const tabs: [Tab, string][] = [
    ["giao_viec", `Giao việc (${taskCount})`],
    ["ket_luan", `Kết luận (${issueCount})`],
    ["dien_bien", "Diễn biến"],
    ["thong_bao", "Thông báo"],
    ["warnings", `Cảnh báo (${data.warnings.length})`],
    ["audit", "Audit"],
    ["raw", "Raw JSON"],
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex overflow-x-auto border-b-2 border-divider">
        {tabs.map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={`px-3 py-2.5 font-heading text-[12.5px] font-extrabold whitespace-nowrap ${
              tab === value ? "bg-accent text-bg" : "text-neutral-700"
            }`}
          >
            {label}
          </button>
        ))}
        <div className="ml-auto flex min-w-0 items-center truncate px-4 text-xs text-neutral-700">
          MA-MRG · họp {data.meeting_date}
          {data.chair ? ` · chủ trì ${data.chair}` : " · chưa rõ chủ trì"} · {data.segments.length} đoạn ·{" "}
          {formatDurationMs(elapsedMs)}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
        {tab !== "raw" && tab !== "audit" && tab !== "warnings" && tab !== "thong_bao" && (
          <p className="mb-4 text-[12px] text-neutral-600">
            Bấm vào một mục hoặc một trường để tô đúng câu làm bằng chứng trên transcript (fold_trace).
          </p>
        )}
        {tab === "giao_viec" && <MrgAssignments giaoViec={data.giao_viec} selectedKey={selectedKey} onSelect={onSelect} />}
        {tab === "ket_luan" && (
          <MrgConclusions ketLuan={data.ket_luan} taskLabels={taskLabels} selectedKey={selectedKey} onSelect={onSelect} />
        )}
        {tab === "dien_bien" && (
          <MrgThreads dienBien={data.dien_bien} summaries={summaries} selectedKey={selectedKey} onSelect={onSelect} />
        )}
        {tab === "thong_bao" &&
          (data.thong_bao ? (
            <div className="flex flex-col gap-3">
              <div className="flex gap-2.5">
                <button type="button" className="btn btn-secondary" onClick={() => void navigator.clipboard.writeText(data.thong_bao ?? "")}>
                  Sao chép
                </button>
              </div>
              <pre className="m-0 max-w-[90ch] bg-surface p-5 font-body text-[13.5px] leading-relaxed whitespace-pre-wrap">
                {data.thong_bao}
              </pre>
              <p className="text-[12px] text-neutral-600">
                Văn bản do realizer diễn đạt từ JSON Kết luận + Giao việc; nội dung do fold quyết định.
              </p>
            </div>
          ) : (
            <p className="text-[13px] text-neutral-700">Realizer đang tắt nên không có văn bản thông báo.</p>
          ))}
        {tab === "warnings" && <MrgWarnings warnings={data.warnings} />}
        {tab === "audit" && <MrgAudit report={data.report} />}
        {tab === "raw" && (
          <pre className="overflow-x-auto bg-neutral-900 p-4 text-[12px] leading-relaxed text-neutral-100">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
