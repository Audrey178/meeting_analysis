import { useEffect, useMemo, useRef } from "react";
import type { EvidenceRef, TranscriptItem, TurnOut } from "../api/types";
import { initialsOf, speakerColor, speakerName } from "../lib/format";
import { Avatar } from "./agentic/primitives";

interface TranscriptPanelProps {
  turns: TurnOut[] | null;
  items: TranscriptItem[] | null;
  /** Bằng chứng đang chọn: turn + (tùy chọn) span ký tự. Span null = tô cả turn (pipeline agentic). */
  selectedEvidence: EvidenceRef[] | null;
}

// Dạng native có speaker; STT export có speaker_name.
function itemSpeaker(item: TranscriptItem): string | null {
  const value = item.speaker ?? (typeof item.speaker_name === "string" ? item.speaker_name : null);
  return value && value.trim() ? value.trim() : null;
}

/** Cắt text thành các mảnh, đánh dấu mảnh nằm trong một span được chọn (span gộp nếu chồng nhau). */
function highlight(text: string, spans: [number, number][]) {
  if (spans.length === 0) return [{ text, hit: false }];
  const sorted = [...spans].sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const [start, end] of sorted) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([Math.max(0, start), Math.min(text.length, end)]);
  }
  const parts: { text: string; hit: boolean }[] = [];
  let cursor = 0;
  for (const [start, end] of merged) {
    if (start > cursor) parts.push({ text: text.slice(cursor, start), hit: false });
    parts.push({ text: text.slice(start, end), hit: true });
    cursor = end;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), hit: false });
  return parts;
}

export function TranscriptPanel({ turns, items, selectedEvidence }: TranscriptPanelProps) {
  const tracing = turns !== null && selectedEvidence !== null;
  const scrollRef = useRef<HTMLDivElement>(null);

  const evidenceByTurn = useMemo(() => {
    const map = new Map<string, [number, number][]>();
    for (const ref of selectedEvidence ?? []) {
      const spans = map.get(ref.turn_id) ?? [];
      if (ref.span) spans.push(ref.span);
      map.set(ref.turn_id, spans);
    }
    return map;
  }, [selectedEvidence]);

  // Cuộn tới turn bằng chứng đầu tiên mỗi khi đổi lựa chọn.
  useEffect(() => {
    if (!tracing || !turns) return;
    const first = turns.find((turn) => evidenceByTurn.has(turn.turn_id));
    if (!first) return;
    const node = scrollRef.current?.querySelector<HTMLElement>(`[data-turn-id="${CSS.escape(first.turn_id)}"]`);
    node?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [tracing, turns, evidenceByTurn]);

  const speakers = useMemo(() => {
    const names = new Set<string>();
    for (const turn of turns ?? []) if (turn.speaker) names.add(turn.speaker);
    for (const item of items ?? []) {
      const speaker = itemSpeaker(item);
      if (speaker) names.add(speaker);
    }
    return names.size;
  }, [turns, items]);

  return (
    <div className="flex min-h-0 flex-col border-r-2 border-divider bg-surface">
      <div className="flex items-center gap-2.5 border-b border-divider px-4.5 py-3">
        <span className="font-heading text-[11px] font-extrabold tracking-[0.1em] text-neutral-800 uppercase">
          Transcript
        </span>
        {(turns || items) && (
          <span className="text-[11.5px] text-neutral-600">
            {turns ? `${turns.length} lượt nói` : `${items!.length} mục · xem trước`} · {speakers} người nói
          </span>
        )}
        {tracing && (
          <span className="ml-auto bg-accent-100 px-2 py-0.5 text-[11px] font-semibold text-accent-800">
            {evidenceByTurn.size} lượt khớp
          </span>
        )}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {turns ? (
          turns.map((turn, index) => {
            const spans = evidenceByTurn.get(turn.turn_id);
            const hit = tracing && spans !== undefined;
            const previous = index > 0 ? turns[index - 1] : null;
            const sameSpeaker = previous?.speaker === turn.speaker;
            return (
              <div key={turn.turn_id}>
                <div
                  data-turn-id={turn.turn_id}
                  className={`flex gap-3 border-l-2 px-4 transition-opacity ${sameSpeaker ? "pt-0.5 pb-2.5" : "pt-3 pb-2.5"} ${
                    hit ? "border-l-accent bg-accent-100" : `border-l-transparent ${tracing ? "opacity-40" : ""}`
                  }`}
                >
                  <div className="w-6 flex-none">
                    {!sameSpeaker && (
                      <Avatar
                        size="sm"
                        label={turn.speaker ? initialsOf(turn.speaker) : "?"}
                        color={speakerColor(turn.speaker)}
                        muted={!turn.speaker}
                      />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    {!sameSpeaker && (
                      <div className="mb-0.5 flex items-baseline gap-2">
                        <span className="truncate text-[12px] font-semibold" style={{ color: speakerColor(turn.speaker) }}>
                          {turn.speaker ? speakerName(turn.speaker) : "Không rõ người nói"}
                        </span>
                        <span className="ml-auto flex-none font-mono text-[10px] text-neutral-500">{turn.turn_id}</span>
                      </div>
                    )}
                    <div className="text-[12.5px] leading-relaxed">
                      {hit && spans && spans.length > 0
                        ? highlight(turn.text, spans).map((part, partIdx) =>
                            part.hit ? (
                              <mark key={partIdx} className="bg-accent-300 text-text">
                                {part.text}
                              </mark>
                            ) : (
                              <span key={partIdx}>{part.text}</span>
                            ),
                          )
                        : turn.text}
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        ) : items && items.length > 0 ? (
          items.map((item, index) => {
            const speaker = itemSpeaker(item);
            const text = item.text ?? (typeof item.segment === "string" ? item.segment : "");
            const sameSpeaker = index > 0 && itemSpeaker(items[index - 1]) === speaker;
            return (
              <div key={item.id ?? index} className={`flex gap-3 px-4 ${sameSpeaker ? "pt-0.5 pb-2" : "pt-3 pb-2"}`}>
                <div className="w-6 flex-none">
                  {!sameSpeaker && (
                    <Avatar size="sm" label={speaker ? initialsOf(speaker) : "?"} color={speakerColor(speaker)} muted={!speaker} />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  {!sameSpeaker && (
                    <div className="mb-0.5 truncate text-[12px] font-semibold" style={{ color: speakerColor(speaker) }}>
                      {speaker ? speakerName(speaker) : "Không rõ người nói"}
                    </div>
                  )}
                  <div className="text-[12.5px] leading-relaxed text-neutral-800">{text}</div>
                </div>
              </div>
            );
          })
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-10 text-center">
            <span className="font-heading text-[15px] font-extrabold text-neutral-700">Chưa có transcript</span>
            <span className="text-[12.5px] text-neutral-600">
              Dán JSON hoặc chọn tệp ở bên phải -- transcript sẽ hiện ở đây để kiểm tra trước khi phân tích.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
