import type { DecisionOut, TopicOut } from "../api/types";
import { CitationCount, EmptyState, EvidenceItem, VerificationTag } from "./agentic/primitives";

interface DecisionBlockProps {
  decisions: DecisionOut[];
  topics: TopicOut[];
  selectedPointKey: string | null;
  onSelectPoint: (key: string, evidenceIds: string[]) => void;
}

// Flat list of verified decisions from the API, grouped here by topic for
// reading (no synthesized administrative paragraph -- that was
// `conclusion_agent`, removed in M6). Numbering runs across the whole meeting
// so "Kết luận 3" means the same thing whichever topic it sits under.
export function DecisionBlock({ decisions, topics, selectedPointKey, onSelectPoint }: DecisionBlockProps) {
  if (decisions.length === 0) {
    return <EmptyState>Không có kết luận nào được xác nhận.</EmptyState>;
  }

  const numbered = decisions.map((decision, idx) => ({ decision, idx }));
  const knownTopicIds = new Set(topics.map((topic) => topic.segment_id));
  const sections = [
    ...topics.map((topic, topicIdx) => ({
      key: topic.segment_id,
      heading: `${String(topicIdx + 1).padStart(2, "0")} · ${topic.title || "(chưa có tiêu đề)"}`,
      items: numbered.filter(({ decision }) => decision.segment_id === topic.segment_id),
    })),
    {
      key: "__other",
      heading: "Khác",
      items: numbered.filter(({ decision }) => !knownTopicIds.has(decision.segment_id)),
    },
  ].filter((section) => section.items.length > 0);

  return (
    <div className="flex flex-col gap-5">
      {sections.map((section) => (
        <section key={section.key}>
          <h6 className="mb-1.5 text-neutral-700">{section.heading}</h6>
          <ol className="m-0 list-none bg-surface p-1.5">
            {section.items.map(({ decision, idx }) => {
              const key = `decision:${idx}`;
              return (
                <li key={key}>
                  <EvidenceItem
                    selected={key === selectedPointKey}
                    onSelect={() => onSelectPoint(key, decision.evidence_ids)}
                    quotes={decision.quotes}
                    leading={
                      <span className="w-6 flex-none pt-px text-right font-heading text-[13px] font-extrabold text-accent">
                        {idx + 1}
                      </span>
                    }
                    trailing={<CitationCount count={decision.citation_count} />}
                    meta={
                      decision.verification && decision.verification !== "rule" ? (
                        <VerificationTag verification={decision.verification} />
                      ) : undefined
                    }
                  >
                    {decision.text}
                  </EvidenceItem>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
