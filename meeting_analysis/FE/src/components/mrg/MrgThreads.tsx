import type { MrgSegmentThreads } from "../../api/types";
import { ACT_LABEL, type SelectEvidence, THREAD_KIND_LABEL } from "../../lib/mrg";
import { TraceButton } from "./TraceButton";

interface MrgThreadsProps {
  dienBien: MrgSegmentThreads[];
  summaries: Record<string, string>;
  selectedKey: string | null;
  onSelect: SelectEvidence;
}

// Diễn biến = các thread responds_to theo đoạn (SPEC 5.3). Narrative do realizer diễn đạt từ đúng các lượt
// trong thread; người nói không suy được (turn nghi gộp) hiện là "một thành viên" thay vì đoán tên.
export function MrgThreads({ dienBien, summaries, selectedKey, onSelect }: MrgThreadsProps) {
  if (dienBien.length === 0) {
    return <p className="text-[13px] text-neutral-700">Không có diễn biến nào được trích.</p>;
  }
  return (
    <div className="flex flex-col gap-7">
      {dienBien.map((segment) => (
        <div key={segment.segment_id}>
          <div className="flex items-baseline gap-3">
            <span className="font-mono text-[11px] text-accent">{segment.segment_id}</span>
            <h4 className="m-0 text-[19px]">{segment.title || "(chưa có tiêu đề)"}</h4>
          </div>
          {summaries[segment.segment_id] && (
            <p className="mt-1.5 mb-3 max-w-[78ch] text-[13px] text-neutral-800">{summaries[segment.segment_id]}</p>
          )}
          <div className="flex flex-col gap-3">
            {segment.threads.map((thread) => {
              const evidence = thread.turns.flatMap((turn) => turn.evidence);
              return (
                <div key={thread.thread_id} className="border-t border-divider pt-2">
                  <TraceButton traceKey={`db:${thread.thread_id}`} evidence={evidence} selectedKey={selectedKey}
                    onSelect={onSelect} className="flex w-full flex-col gap-1 px-2.5 py-1.5">
                    <span className="flex items-baseline gap-2.5">
                      <span className="tag tag-neutral">{THREAD_KIND_LABEL[thread.kind] ?? thread.kind}</span>
                      <span className="text-[13.5px] leading-snug">{thread.narrative || "—"}</span>
                    </span>
                  </TraceButton>
                  <div className="mt-1 flex flex-col pl-4">
                    {thread.turns.map((turn) => (
                      <TraceButton key={turn.act_id} traceKey={`db:${turn.act_id}`} evidence={turn.evidence}
                        selectedKey={selectedKey} onSelect={onSelect}
                        className="grid grid-cols-[150px_80px_minmax(0,1fr)] gap-2.5 px-2.5 py-1 text-[12.5px]">
                        <span className={turn.speaker_source === "unreliable" ? "text-neutral-600 italic" : "font-semibold"}>
                          {turn.speaker}
                        </span>
                        <span className="text-accent-700">{ACT_LABEL[turn.act_type] ?? turn.act_type}</span>
                        <span className="text-neutral-800">{turn.content}</span>
                      </TraceButton>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
