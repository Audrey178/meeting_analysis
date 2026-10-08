import type { ReactNode } from "react";
import type { MrgKetLuan } from "../../api/types";
import { type SelectEvidence, traceToEvidence } from "../../lib/mrg";
import { TraceButton } from "./TraceButton";

interface MrgConclusionsProps {
  ketLuan: MrgKetLuan;
  taskLabels: Record<string, string>;
  selectedKey: string | null;
  onSelect: SelectEvidence;
}

function Section({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <div className="mb-6">
      <h6 className="mb-2">
        {title} ({count})
      </h6>
      {count === 0 ? <p className="text-[13px] text-neutral-600">Không có.</p> : <div className="flex flex-col gap-1">{children}</div>}
    </div>
  );
}

// Trạng thái từng vấn đề do fold_issue quyết định bằng luật (SPEC 5.2), không do LLM viết:
// câu chốt có rào đón / bị phản biện sau đó vẫn nằm ở "Chưa thống nhất".
export function MrgConclusions({ ketLuan, taskLabels, selectedKey, onSelect }: MrgConclusionsProps) {
  const tasks = (ids: string[]) => ids.map((id) => taskLabels[id] ?? id).join("; ");
  return (
    <div>
      <Section title="Đã thống nhất" count={ketLuan.resolved.length}>
        {ketLuan.resolved.map((item) => (
          <TraceButton key={item.issue_id} traceKey={`kl:${item.issue_id}`} evidence={traceToEvidence(item.fold_trace)}
            selectedKey={selectedKey} onSelect={onSelect} className="flex flex-col gap-0.5 px-2.5 py-2 text-[13px]">
            <span className="font-semibold">{item.issue}</span>
            <span>→ {item.conclusion ?? "—"}</span>
            <span className="text-[12px] text-neutral-700">
              {item.decided_by ? `Người chốt: ${item.decided_by}` : "Người chốt: chưa xác định"}
              {item.spawned_tasks.length > 0 && ` · Việc kéo theo: ${tasks(item.spawned_tasks)}`}
              {item.basis.length > 0 && ` · Căn cứ: ${item.basis.join("; ")}`}
            </span>
          </TraceButton>
        ))}
      </Section>

      <Section title="Thống nhất có điều kiện" count={ketLuan.resolved_conditional.length}>
        {ketLuan.resolved_conditional.map((item) => (
          <TraceButton key={item.issue_id} traceKey={`kl:${item.issue_id}`} evidence={traceToEvidence(item.fold_trace)}
            selectedKey={selectedKey} onSelect={onSelect} className="flex flex-col gap-0.5 px-2.5 py-2 text-[13px]">
            <span className="font-semibold">{item.issue}</span>
            <span>→ {item.conclusion ?? "—"}</span>
            <span className="text-[12px] text-accent-700">Điều kiện: {item.condition}</span>
            {item.follow_up.length > 0 && <span className="text-[12px] text-neutral-700">Việc tiếp: {tasks(item.follow_up)}</span>}
          </TraceButton>
        ))}
      </Section>

      <Section title="Hoãn" count={ketLuan.deferred.length}>
        {ketLuan.deferred.map((item) => (
          <TraceButton key={item.issue_id} traceKey={`kl:${item.issue_id}`} evidence={traceToEvidence(item.fold_trace)}
            selectedKey={selectedKey} onSelect={onSelect} className="flex items-baseline gap-2.5 px-2.5 py-2 text-[13px]">
            <span className="flex-1 font-semibold">{item.issue}</span>
            {item.until && <span className="text-[12px] text-neutral-700">đến: {item.until}</span>}
          </TraceButton>
        ))}
      </Section>

      <Section title="Chưa thống nhất / còn mở" count={ketLuan.open.length}>
        {ketLuan.open.map((item) => (
          <TraceButton key={item.issue_id} traceKey={`kl:${item.issue_id}`} evidence={traceToEvidence(item.fold_trace)}
            selectedKey={selectedKey} onSelect={onSelect} className="flex flex-col gap-0.5 px-2.5 py-2 text-[13px]">
            <span className="flex items-baseline gap-2.5">
              <span className="flex-1 font-semibold">{item.issue}</span>
              {item.owner_missing && <span className="tag tag-outline">chưa có người phụ trách</span>}
            </span>
            {item.alternatives.length > 0 && (
              <span className="text-[12px] text-neutral-700">Phương án: {item.alternatives.join(" / ")}</span>
            )}
            {item.follow_up.length > 0 && <span className="text-[12px] text-neutral-700">Việc tiếp: {tasks(item.follow_up)}</span>}
          </TraceButton>
        ))}
      </Section>
    </div>
  );
}
