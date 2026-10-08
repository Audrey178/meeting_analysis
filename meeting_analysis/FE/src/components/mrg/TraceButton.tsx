import type { ReactNode } from "react";
import type { EvidenceRef } from "../../api/types";
import type { SelectEvidence } from "../../lib/mrg";

interface TraceButtonProps {
  traceKey: string;
  evidence: EvidenceRef[];
  selectedKey: string | null;
  onSelect: SelectEvidence;
  children: ReactNode;
  className?: string;
  title?: string;
}

// Mọi mục của MA-MRG đều truy vết được: bấm để tô các turn/span làm bằng chứng (fold_trace) trên transcript.
// Mục không có bằng chứng thì không bấm được (và hiện như vậy), thay vì giả vờ có.
export function TraceButton({ traceKey, evidence, selectedKey, onSelect, children, className = "", title }: TraceButtonProps) {
  const selected = traceKey === selectedKey;
  const disabled = evidence.length === 0;
  return (
    <button
      type="button"
      disabled={disabled}
      title={disabled ? "Không có bằng chứng truy vết" : (title ?? "Bấm để xem bằng chứng trên transcript")}
      onClick={() => onSelect(traceKey, evidence)}
      className={`border-0 border-l-2 text-left ${
        selected
          ? "border-l-accent bg-accent-100"
          : `border-l-transparent bg-transparent ${disabled ? "cursor-default" : "hover:bg-accent-100"}`
      } ${className}`}
    >
      {children}
    </button>
  );
}
