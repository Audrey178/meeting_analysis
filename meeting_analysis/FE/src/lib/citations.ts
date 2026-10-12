import type { Citation, ItemId, TranscriptItem } from "../api/types";

/** Khoá so sánh của mã item: document trả mã gốc (số khi xuất từ STT), lượt nói giữ dạng chuỗi. */
export function itemKey(id: ItemId): string {
  return String(id).trim();
}

/** Nội dung một item transcript (dạng native có `text`, STT export có `segment`). */
export function itemText(item: TranscriptItem): string {
  if (typeof item.text === "string") return item.text;
  return typeof item.segment === "string" ? item.segment : "";
}

/** Tra item theo mã: nội dung và vị trí trong transcript (để gộp các item liền nhau thành một trích dẫn). */
export interface TranscriptIndex {
  text: Map<string, string>;
  position: Map<string, number>;
}

export function buildTranscriptIndex(items: TranscriptItem[]): TranscriptIndex {
  const text = new Map<string, string>();
  const position = new Map<string, number>();
  items.forEach((item, index) => {
    const key = itemKey(item.id);
    text.set(key, itemText(item));
    position.set(key, index);
  });
  return { text, position };
}

/** Trích dẫn để hiện dưới một mục: các item liền nhau trong transcript nối thành một đoạn. */
export function quotesOf(index: TranscriptIndex, segmentIds: ItemId[]): string[] {
  const keys = segmentIds.map(itemKey).filter((key) => index.text.has(key));
  keys.sort((a, b) => index.position.get(a)! - index.position.get(b)!);
  const quotes: string[] = [];
  let previous = -2;
  for (const key of keys) {
    const position = index.position.get(key)!;
    const text = index.text.get(key)!;
    if (position === previous + 1 && quotes.length > 0) quotes[quotes.length - 1] += ` ${text}`;
    else quotes.push(text);
    previous = position;
  }
  return quotes;
}

export function citation(segmentIds: ItemId[], turnIds: string[]): Citation {
  return { segmentIds, turnIds };
}
