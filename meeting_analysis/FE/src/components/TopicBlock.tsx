import { useState } from "react";
import type { Citation, ContentTopic } from "../api/types";
import { quotesOf, type TranscriptIndex } from "../lib/citations";
import { initialsOf, speakerColor, speakerName, speakerRole, topicNumber } from "../lib/format";
import { Avatar, CitationCount, EvidenceItem, SectionLabel } from "./agentic/primitives";

interface TopicBlockProps {
  topic: ContentTopic;
  index: number;
  assignmentCount: number;
  decisionCount: number;
  transcript: TranscriptIndex;
  selectedKey: string | null;
  onSelect: (key: string, citation: Citation) => void;
}

function SpeakerChip({ name }: { name: string }) {
  return (
    <span className="flex items-center gap-1.5" title={speakerRole(name) ?? undefined}>
      <Avatar size="sm" label={initialsOf(name)} color={speakerColor(name)} />
      <span className="text-[12px] font-semibold" style={{ color: speakerColor(name) }}>
        {speakerName(name)}
      </span>
    </span>
  );
}

/** Khoảng item của chủ đề, vd. "dòng 92–106". */
function spanLabel(topic: ContentTopic): string | null {
  const [first, last] = topic.extracted.span.segment_ids;
  if (first === undefined) return null;
  return last === undefined || last === first ? `dòng ${first}` : `dòng ${first}–${last}`;
}

export function TopicBlock({
  topic,
  index,
  assignmentCount,
  decisionCount,
  transcript,
  selectedKey,
  onSelect,
}: TopicBlockProps) {
  const [open, setOpen] = useState(true);
  const { content, discussion_points: points } = topic.extracted;
  const speakerCount = new Set(points.flatMap((point) => point.speakers)).size;
  const span = spanLabel(topic);

  return (
    <section className="mb-4 bg-surface">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-start gap-4 px-5 pt-4 pb-3 text-left"
      >
        <span className="font-heading text-[28px] leading-none font-extrabold text-accent">{topicNumber(index)}</span>
        <span className="flex min-w-0 flex-1 flex-col gap-1.5">
          <span className="font-heading text-[17px] leading-snug font-extrabold">
            {content.title || "(chưa có tiêu đề)"}
          </span>
          <span className="flex flex-wrap gap-1.5">
            <span className="tag tag-neutral">{speakerCount} người nói</span>
            <span className="tag tag-neutral">{points.length} ý thảo luận</span>
            {assignmentCount > 0 && <span className="tag tag-neutral">{assignmentCount} việc giao</span>}
            {decisionCount > 0 && <span className="tag tag-neutral">{decisionCount} kết luận</span>}
            {span && <span className="tag tag-muted font-mono">{span}</span>}
          </span>
        </span>
        <span className="pt-1 font-mono text-[11px] text-neutral-600">{open ? "thu gọn ▴" : "mở ▾"}</span>
      </button>

      {open && (
        <div className="px-5 pb-4">
          {content.summary && (
            <p className="mb-4 max-w-[80ch] border-l-2 border-l-neutral-400 pl-3 text-[13.5px] text-neutral-800">
              {content.summary}
            </p>
          )}
          {points.length > 0 && <SectionLabel>Ý thảo luận</SectionLabel>}
          <ol className="m-0 flex list-none flex-col p-0">
            {points.map((point) => {
              const key = `content:${point.point_id}`;
              return (
                <li key={key} className="border-t border-divider py-1">
                  <EvidenceItem
                    selected={key === selectedKey}
                    onSelect={() => onSelect(key, { segmentIds: point.segment_ids, turnIds: point.turn_ids })}
                    quotes={quotesOf(transcript, point.segment_ids)}
                    trailing={<CitationCount count={point.segment_ids.length} />}
                    meta={
                      point.speakers.length > 0 ? (
                        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                          {point.speakers.map((name) => (
                            <SpeakerChip key={name} name={name} />
                          ))}
                        </span>
                      ) : undefined
                    }
                  >
                    {point.text}
                  </EvidenceItem>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </section>
  );
}
