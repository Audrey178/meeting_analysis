import { useState } from "react";
import type { DebateRecordOut } from "../api/types";
import { EmptyState } from "./agentic/primitives";

type Verdict = "keep" | "revise" | "drop";
type Filter = "all" | Verdict;

const VERDICT_STYLE: Record<Verdict, { label: string; className: string }> = {
  keep: { label: "Giữ", className: "tag tag-ok" },
  revise: { label: "Giữ · sửa người phụ trách", className: "tag tag-outline" },
  drop: { label: "Bỏ", className: "tag tag-accent" },
};

const KIND_LABEL = { action: "Việc giao", decision: "Kết luận" } as const;

function verdictOf(record: DebateRecordOut): Verdict {
  return record.verdict ?? (record.kept ? "keep" : "drop");
}

interface VerificationBlockProps {
  records: DebateRecordOut[];
  topicIndexById: Record<string, number>;
  selectedPointKey: string | null;
  onSelectPoint: (key: string, evidenceIds: string[]) => void;
}

// Audit view of every candidate Evidence-Check flagged as uncertain: why it
// was flagged, both sides of the debate, and the judge's ruling. Clicking the
// deciding turn highlights it in the transcript.
export function VerificationBlock({ records, topicIndexById, selectedPointKey, onSelectPoint }: VerificationBlockProps) {
  const [filter, setFilter] = useState<Filter>("all");

  if (records.length === 0) {
    return <EmptyState>Không có mục nào bị nghi ngờ -- mọi việc giao và kết luận đều qua kiểm tra bằng luật.</EmptyState>;
  }

  const counts: Record<Filter, number> = { all: records.length, keep: 0, revise: 0, drop: 0 };
  for (const record of records) counts[verdictOf(record)] += 1;
  const visible = records
    .map((record, idx) => ({ record, idx }))
    .filter(({ record }) => filter === "all" || verdictOf(record) === filter);

  const filters: [Filter, string][] = [
    ["all", "Tất cả"],
    ["keep", "Giữ"],
    ["revise", "Sửa"],
    ["drop", "Bỏ"],
  ];

  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 max-w-[80ch] text-[12.5px] text-neutral-700">
        Các mục dưới đây bị Evidence-Check đánh dấu <em>chưa chắc chắn</em> (người phụ trách không rõ, lượt chốt chỉ là
        đề xuất, agent tự khai là đề xuất/báo cáo…) và được hai agent tranh luận trước khi trọng tài quyết định.
      </p>
      <div className="flex gap-1.5">
        {filters.map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            className={`btn px-3 py-1 text-[12px] ${filter === value ? "btn-primary" : "btn-secondary"}`}
          >
            {label} ({counts[value]})
          </button>
        ))}
      </div>

      {visible.map(({ record, idx }) => {
        const verdict = verdictOf(record);
        const style = VERDICT_STYLE[verdict];
        const key = `debate:${idx}`;
        const topicIndex = topicIndexById[record.segment_id];
        const deciding = record.deciding_turn_id;
        return (
          <article key={key} className="bg-surface">
            <header className="flex flex-wrap items-center gap-1.5 border-b border-divider px-4 py-2.5">
              <span className={style.className}>{style.label}</span>
              <span className="tag tag-neutral">{KIND_LABEL[record.kind]}</span>
              {topicIndex !== undefined && (
                <span className="tag tag-muted">Chủ đề {String(topicIndex + 1).padStart(2, "0")}</span>
              )}
            </header>
            <div className="flex flex-col gap-3 px-4 py-3">
              <div className={`text-[14px] leading-snug ${verdict === "drop" ? "text-neutral-600 line-through" : ""}`}>
                {record.candidate_text}
              </div>
              {verdict === "revise" && record.final_text && (
                <div className="text-[14px] leading-snug">
                  <span className="mr-1.5 font-heading text-[11px] font-extrabold text-accent uppercase">Sửa thành</span>
                  {record.final_text}
                </div>
              )}
              {record.reasons.length > 0 && (
                <ul className="m-0 flex list-none flex-col gap-1 p-0">
                  {record.reasons.map((reason, reasonIdx) => (
                    <li key={reasonIdx} className="text-[12px] text-neutral-700">
                      <span className="mr-1.5 text-accent">!</span>
                      {reason}
                    </li>
                  ))}
                </ul>
              )}
              <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
                <div className="border-l-2 border-l-ok bg-bg px-3 py-2">
                  <div className="mb-1 font-heading text-[11px] font-extrabold tracking-[0.06em] text-ok uppercase">
                    Ủng hộ
                  </div>
                  <p className="m-0 text-[12.5px] leading-snug">{record.support_argument || "(không có)"}</p>
                </div>
                <div className="border-l-2 border-l-accent bg-bg px-3 py-2">
                  <div className="mb-1 font-heading text-[11px] font-extrabold tracking-[0.06em] text-accent uppercase">
                    Phản biện
                  </div>
                  <p className="m-0 text-[12.5px] leading-snug">{record.oppose_argument || "(không có)"}</p>
                </div>
              </div>
              <div className="flex items-start gap-3 border-t border-divider pt-2.5">
                <span className="font-heading text-[11px] font-extrabold tracking-[0.06em] text-neutral-700 uppercase">
                  Trọng tài
                </span>
                <p className="m-0 flex-1 text-[12.5px] leading-snug">{record.reasoning || "(không có giải thích)"}</p>
                {deciding && (
                  <button
                    type="button"
                    onClick={() => onSelectPoint(key, [deciding])}
                    className={`btn btn-ghost flex-none font-mono text-[11px] ${
                      selectedPointKey === key ? "bg-accent-100" : ""
                    }`}
                    title="Tô lượt nói trọng tài dựa vào trên transcript"
                  >
                    {deciding} →
                  </button>
                )}
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
