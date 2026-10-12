import { Fragment, useEffect, useMemo, useRef } from "react";
import type { Citation, TranscriptItem, TranscriptTurn } from "../api/types";
import { itemKey, itemText } from "../lib/citations";
import { initialsOf, speakerColor, speakerName } from "../lib/format";
import { Avatar } from "./agentic/primitives";

interface TranscriptPanelProps {
  /** Lượt nói của document Diễn biến (mỗi lượt gồm các item liền nhau cùng người nói); null khi chưa có. */
  turns: TranscriptTurn[] | null;
  /** Item của request: xem trước khi chưa có lượt nói, và nội dung từng item để tô mức item. */
  items: TranscriptItem[] | null;
  /** Bằng chứng đang chọn: item được trích (tô từng dòng), hoặc chỉ lượt nói (tô cả lượt). */
  selected: Citation | null;
}

// Dạng native có speaker; STT export có speaker_name.
function itemSpeaker(item: TranscriptItem): string | null {
  const value = item.speaker ?? (typeof item.speaker_name === "string" ? item.speaker_name : null);
  return value && value.trim() ? value.trim() : null;
}

export function TranscriptPanel({ turns, items, selected }: TranscriptPanelProps) {
  const tracing = turns !== null && selected !== null;
  const scrollRef = useRef<HTMLDivElement>(null);

  const textOfItem = useMemo(() => new Map((items ?? []).map((item) => [itemKey(item.id), itemText(item)])), [items]);
  const selectedItems = useMemo(() => new Set((selected?.segmentIds ?? []).map(itemKey)), [selected]);
  const selectedTurns = useMemo(() => new Set(selected?.turnIds ?? []), [selected]);

  /** Lượt nói được tô: chứa item được trích, hoặc được chọn cả lượt. */
  const hitTurns = useMemo(() => {
    const hits = new Set<string>();
    for (const turn of turns ?? []) {
      if (selectedTurns.has(turn.turn_id) || turn.segment_ids.some((id) => selectedItems.has(itemKey(id)))) {
        hits.add(turn.turn_id);
      }
    }
    return hits;
  }, [turns, selectedItems, selectedTurns]);

  // Cuộn tới lượt bằng chứng đầu tiên mỗi khi đổi lựa chọn.
  useEffect(() => {
    if (!tracing || !turns) return;
    const first = turns.find((turn) => hitTurns.has(turn.turn_id));
    if (!first) return;
    const node = scrollRef.current?.querySelector<HTMLElement>(`[data-turn-id="${CSS.escape(first.turn_id)}"]`);
    node?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [tracing, turns, hitTurns]);

  const speakers = useMemo(() => {
    const names = new Set<string>();
    for (const turn of turns ?? []) if (turn.speaker) names.add(turn.speaker);
    for (const item of items ?? []) {
      const speaker = itemSpeaker(item);
      if (speaker) names.add(speaker);
    }
    return names.size;
  }, [turns, items]);

  /** Nội dung lượt nói: từng item, item được trích tô đậm; thiếu nội dung item thì in cả lượt. */
  function renderTurnText(turn: TranscriptTurn, hit: boolean) {
    const parts = turn.segment_ids.map((id) => ({ key: itemKey(id), text: textOfItem.get(itemKey(id)) }));
    if (parts.length === 0 || parts.some((part) => part.text === undefined)) return turn.text;
    return parts.map((part, index) => (
      <Fragment key={part.key}>
        {index > 0 && " "}
        {hit && selectedItems.has(part.key) ? (
          <mark className="bg-accent-300 text-text" title={`dòng ${part.key}`}>
            {part.text}
          </mark>
        ) : (
          <span title={`dòng ${part.key}`}>{part.text}</span>
        )}
      </Fragment>
    ));
  }

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
            {selectedItems.size > 0 ? `${selectedItems.size} dòng · ` : ""}
            {hitTurns.size} lượt khớp
          </span>
        )}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {turns ? (
          turns.map((turn, index) => {
            const hit = tracing && hitTurns.has(turn.turn_id);
            const previous = index > 0 ? turns[index - 1] : null;
            const sameSpeaker = previous?.speaker === turn.speaker;
            return (
              <div
                key={turn.turn_id}
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
                  <div className="text-[12.5px] leading-relaxed">{renderTurnText(turn, hit)}</div>
                </div>
              </div>
            );
          })
        ) : items && items.length > 0 ? (
          items.map((item, index) => {
            const speaker = itemSpeaker(item);
            const sameSpeaker = index > 0 && itemSpeaker(items[index - 1]) === speaker;
            return (
              <div key={itemKey(item.id ?? index)} className={`flex gap-3 px-4 ${sameSpeaker ? "pt-0.5 pb-2" : "pt-3 pb-2"}`}>
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
                  <div className="text-[12.5px] leading-relaxed text-neutral-800">{itemText(item)}</div>
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
