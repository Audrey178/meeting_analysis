import { useState } from "react";
import type { TopicOut } from "../api/types";
import { initialsOf, speakerColor, speakerName, speakerRole } from "../lib/format";
import { Avatar, CitationCount, EvidenceItem, SectionLabel } from "./agentic/primitives";

interface TopicBlockProps {
  topic: TopicOut;
  index: number;
  assignmentCount: number;
  decisionCount: number;
  selectedPointKey: string | null;
  onSelectPoint: (key: string, evidenceIds: string[]) => void;
}

export function TopicBlock({
  topic,
  index,
  assignmentCount,
  decisionCount,
  selectedPointKey,
  onSelectPoint,
}: TopicBlockProps) {
  const [open, setOpen] = useState(true);
  const pointCount = topic.speakers.reduce((sum, speaker) => sum + speaker.points.length, 0);

  return (
    <section className="mb-4 bg-surface">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-start gap-4 px-5 pt-4 pb-3 text-left"
      >
        <span className="font-heading text-[28px] leading-none font-extrabold text-accent">
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="font-heading text-[17px] leading-snug font-extrabold">
            {topic.title || "(chưa có tiêu đề)"}
          </span>
          <span className="flex flex-wrap gap-1.5">
            <span className="tag tag-neutral">{topic.speakers.length} người nói</span>
            <span className="tag tag-neutral">{pointCount} luận điểm</span>
            {assignmentCount > 0 && <span className="tag tag-neutral">{assignmentCount} việc giao</span>}
            {decisionCount > 0 && <span className="tag tag-neutral">{decisionCount} kết luận</span>}
          </span>
        </span>
        <span className="pt-1 font-mono text-[11px] text-neutral-600">{open ? "thu gọn ▴" : "mở ▾"}</span>
      </button>

      {open && (
        <div className="px-5 pb-4">
          {topic.summary && (
            <p className="mb-4 max-w-[80ch] border-l-2 border-l-neutral-400 pl-3 text-[13.5px] text-neutral-800">
              {topic.summary}
            </p>
          )}
          {topic.speakers.length > 0 && <SectionLabel>Luận điểm theo người nói</SectionLabel>}
          <div className="flex flex-col">
            {topic.speakers.map((speaker, speakerIdx) => (
              <div
                key={`${speaker.full_name}-${speakerIdx}`}
                className="grid grid-cols-[180px_minmax(0,1fr)] gap-3 border-t border-divider py-2"
              >
                <div className="flex items-start gap-2.5 pt-1.5">
                  <Avatar label={initialsOf(speaker.full_name)} color={speakerColor(speaker.full_name)} />
                  <span className="flex min-w-0 flex-col">
                    <span className="text-[13px] leading-tight font-semibold break-words">
                      {speakerName(speaker.full_name)}
                    </span>
                    {speakerRole(speaker.full_name) && (
                      <span className="mt-0.5 text-[11px] leading-tight text-neutral-600">
                        {speakerRole(speaker.full_name)}
                      </span>
                    )}
                  </span>
                </div>
                <div className="flex flex-col">
                  {speaker.points.map((point, pointIdx) => {
                    const key = `${topic.segment_id}:${speakerIdx}:${pointIdx}`;
                    return (
                      <EvidenceItem
                        key={key}
                        selected={key === selectedPointKey}
                        onSelect={() => onSelectPoint(key, point.evidence_ids)}
                        quotes={point.quotes}
                        trailing={<CitationCount count={point.citation_count} />}
                      >
                        {point.text}
                      </EvidenceItem>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
