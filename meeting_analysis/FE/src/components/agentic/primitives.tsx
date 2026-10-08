import type { ReactNode } from "react";
import type { Verification } from "../../api/types";

// Shared building blocks for the agentic result tabs: every clickable item
// (point, assignment, decision) uses EvidenceItem so the click-to-trace
// interaction and the quote reveal look the same everywhere.

export function Avatar({
  label,
  color,
  muted = false,
  size = "md",
}: {
  label: string;
  /** Background color (speaker color); defaults to the text color. */
  color?: string;
  muted?: boolean;
  size?: "sm" | "md";
}) {
  const dimensions = size === "sm" ? "h-6 w-6 text-[10px]" : "h-9 w-9 text-[12px]";
  return (
    <span
      className={`flex flex-none items-center justify-center font-heading font-extrabold ${dimensions} ${
        muted ? "bg-neutral-300 text-neutral-800" : "text-bg"
      }`}
      style={muted ? undefined : { background: color ?? "var(--color-text)" }}
    >
      {label}
    </span>
  );
}

const VERIFICATION_TAG: Record<Verification, { label: string; className: string; title: string } | null> = {
  rule: null,
  debate: {
    label: "qua tranh luận",
    className: "tag tag-ok",
    title: "Bị Evidence-Check nghi ngờ, Debate+Judge xác nhận giữ lại",
  },
  fallback: {
    label: "chưa kiểm chứng đủ",
    className: "tag tag-accent",
    title: "Bị nghi ngờ nhưng được giữ theo luật an toàn (debate lỗi hoặc không chạy)",
  },
  consensus: {
    label: "đồng thuận",
    className: "tag tag-ok",
    title: "Bị Evidence-Check nghi ngờ, Verifier và agent trích xuất trao đổi feedback rồi thống nhất giữ lại",
  },
  verifier: {
    label: "theo Verifier",
    className: "tag tag-outline",
    title: "Hết số vòng trao đổi mà chưa đồng thuận, giữ theo kết luận cuối của Verifier",
  },
};

export function VerificationTag({ verification }: { verification?: Verification }) {
  const tag = VERIFICATION_TAG[verification ?? "rule"];
  if (!tag) return null;
  return (
    <span className={tag.className} title={tag.title}>
      {tag.label}
    </span>
  );
}

export function CitationCount({ count }: { count: number }) {
  return (
    <span className="flex-none font-mono text-[11px] text-neutral-600" title="Số lượt nói làm bằng chứng">
      {count} trích dẫn
    </span>
  );
}

interface EvidenceItemProps {
  selected: boolean;
  onSelect: () => void;
  quotes: string[];
  children: ReactNode;
  /** Optional row under the main line (tags, deadline...). */
  meta?: ReactNode;
  leading?: ReactNode;
  /** Small inline element at the right of the main line (e.g. citation count). */
  trailing?: ReactNode;
}

export function EvidenceItem({ selected, onSelect, quotes, children, meta, leading, trailing }: EvidenceItemProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`group flex w-full gap-3 border-0 border-l-2 px-3 py-2.5 text-left text-[13.5px] transition-colors ${
        selected ? "border-l-accent bg-accent-100" : "border-l-transparent bg-transparent hover:bg-neutral-200"
      }`}
    >
      {leading}
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="flex items-baseline gap-3">
          <span className="min-w-0 flex-1 leading-snug">{children}</span>
          {trailing}
        </span>
        {meta && <span className="flex flex-wrap items-center gap-1.5">{meta}</span>}
        {selected && quotes.length > 0 && (
          <span className="mt-1 flex flex-col gap-1.5 border-l-2 border-l-accent-300 pl-3">
            {quotes.map((quote, idx) => (
              <q key={idx} className="block text-[12.5px] leading-snug text-neutral-700 italic">
                {quote}
              </q>
            ))}
          </span>
        )}
      </span>
    </button>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-10 text-center text-[13px] text-neutral-600">{children}</p>;
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-2 font-heading text-[11px] tracking-[0.08em] text-neutral-700 uppercase">{children}</div>
  );
}
