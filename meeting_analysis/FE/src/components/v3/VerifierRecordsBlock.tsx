import { useState } from "react";
import type { VerificationRecordOut } from "../../api/types";
import { EmptyState } from "../agentic/primitives";

type Filter = "all" | "keep" | "revise" | "drop" | "no_consensus";

const VERDICT_STYLE: Record<string, { label: string; className: string }> = {
  keep: { label: "Giữ", className: "tag tag-ok" },
  revise: { label: "Giữ · sửa", className: "tag tag-outline" },
  drop: { label: "Bỏ", className: "tag tag-accent" },
  unresolved: { label: "Chưa kết luận", className: "tag tag-accent" },
};

const DECIDED_BY_LABEL: Record<string, string> = {
  consensus: "đồng thuận",
  verifier: "Verifier (chưa đồng thuận)",
  fallback: "luật an toàn",
};

const STANCE_LABEL: Record<string, string> = {
  accept: "đồng ý",
  amend: "sửa candidate",
  defend: "giữ nguyên, phản biện",
};

const KIND_LABEL = { action: "Việc giao", decision: "Kết luận" } as const;

interface VerifierRecordsBlockProps {
  records: VerificationRecordOut[];
  topicIndexById: Record<string, number>;
  selectedPointKey: string | null;
  onSelectPoint: (key: string, evidenceIds: string[]) => void;
}

function matches(record: VerificationRecordOut, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "no_consensus") return record.decided_by !== "consensus";
  return record.verdict === filter;
}

// Audit view của v3: mỗi mục bị Evidence-Check nghi ngờ, chuỗi tra cứu của Verifier
// (tool + kết quả), các vòng feedback với agent trích xuất và cách ra quyết định cuối.
export function VerifierRecordsBlock({ records, topicIndexById, selectedPointKey, onSelectPoint }: VerifierRecordsBlockProps) {
  const [filter, setFilter] = useState<Filter>("all");

  if (records.length === 0) {
    return <EmptyState>Không có mục nào bị nghi ngờ -- mọi việc giao và kết luận đều qua kiểm tra bằng luật.</EmptyState>;
  }

  const filters: [Filter, string][] = [
    ["all", "Tất cả"],
    ["keep", "Giữ"],
    ["revise", "Sửa"],
    ["drop", "Bỏ"],
    ["no_consensus", "Chưa đồng thuận"],
  ];

  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 max-w-[80ch] text-[12.5px] text-neutral-700">
        Các mục bị Evidence-Check đánh dấu <em>chưa chắc chắn</em>. Verifier tự tra bằng chứng trong cả cuộc họp rồi gửi
        feedback lại cho agent trích xuất; hai bên trao đổi tới khi đồng thuận (hoặc hết số vòng, khi đó theo Verifier).
      </p>
      <div className="flex flex-wrap gap-1.5">
        {filters.map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            className={`btn px-3 py-1 text-[12px] ${filter === value ? "btn-primary" : "btn-secondary"}`}
          >
            {label} ({records.filter((record) => matches(record, value)).length})
          </button>
        ))}
      </div>

      {records
        .filter((record) => matches(record, filter))
        .map((record) => {
          const style = VERDICT_STYLE[record.verdict] ?? VERDICT_STYLE.unresolved;
          const key = `verify:${record.item_key}`;
          const topicIndex = topicIndexById[record.segment_id];
          const deciding = record.deciding_turn_id;
          return (
            <article key={record.item_key} className="bg-surface">
              <header className="flex flex-wrap items-center gap-1.5 border-b border-divider px-4 py-2.5">
                <span className={style.className}>{style.label}</span>
                <span className="tag tag-neutral">{KIND_LABEL[record.kind]}</span>
                {topicIndex !== undefined && (
                  <span className="tag tag-muted">Chủ đề {String(topicIndex + 1).padStart(2, "0")}</span>
                )}
                <span className="ml-auto text-[11.5px] text-neutral-700">
                  quyết định: {DECIDED_BY_LABEL[record.decided_by] ?? record.decided_by}
                </span>
              </header>
              <div className="flex flex-col gap-3 px-4 py-3">
                <div className={`text-[14px] leading-snug ${record.verdict === "drop" ? "text-neutral-600 line-through" : ""}`}>
                  {record.candidate_text}
                </div>
                {record.final_text && record.final_text !== record.candidate_text && (
                  <div className="text-[14px] leading-snug">
                    <span className="mr-1.5 font-heading text-[11px] font-extrabold text-accent uppercase">Sửa thành</span>
                    {record.final_text}
                  </div>
                )}
                {record.reasons.length > 0 && (
                  <ul className="m-0 flex list-none flex-col gap-1 p-0">
                    {record.reasons.map((reason, idx) => (
                      <li key={idx} className="text-[12px] text-neutral-700">
                        <span className="mr-1.5 text-accent">!</span>
                        {reason}
                      </li>
                    ))}
                  </ul>
                )}
                {record.steps.length > 0 && (
                  <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
                    {record.steps.map((step, idx) => (
                      <li key={idx} className="border-l-2 border-l-divider bg-bg px-3 py-2">
                        <div className="font-mono text-[11.5px]">
                          {idx + 1}. {step.action}({step.argument})
                        </div>
                        <pre className="m-0 mt-1 text-[11.5px] leading-snug whitespace-pre-wrap text-neutral-700">
                          {step.observation}
                        </pre>
                      </li>
                    ))}
                  </ol>
                )}
                {record.rounds.length > 1 || record.rounds.some((round) => round.stance) ? (
                  <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
                    {record.rounds.map((round, idx) => (
                      <li key={idx} className="border-l-2 border-l-accent bg-bg px-3 py-2 text-[12px] leading-snug">
                        <div>
                          <span className="font-heading font-extrabold">Vòng {idx + 1} · Verifier: {round.verdict}</span>{" "}
                          {round.feedback}
                        </div>
                        {round.stance && (
                          <div className="mt-1 text-neutral-700">
                            <span className="font-heading font-extrabold">
                              Agent trích xuất ({STANCE_LABEL[round.stance] ?? round.stance}):
                            </span>{" "}
                            {round.response}
                          </div>
                        )}
                      </li>
                    ))}
                  </ol>
                ) : null}
                <div className="flex items-start gap-3 border-t border-divider pt-2.5">
                  <span className="font-heading text-[11px] font-extrabold tracking-[0.06em] text-neutral-700 uppercase">
                    Lý do
                  </span>
                  <p className="m-0 flex-1 text-[12.5px] leading-snug">{record.reasoning || "(không có giải thích)"}</p>
                  {deciding && (
                    <button
                      type="button"
                      onClick={() => onSelectPoint(key, [deciding])}
                      className={`btn btn-ghost flex-none font-mono text-[11px] ${selectedPointKey === key ? "bg-accent-100" : ""}`}
                      title="Tô lượt nói Verifier dựa vào trên transcript"
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
