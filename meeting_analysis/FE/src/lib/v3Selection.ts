import type { V3Part } from "../api/types";

/**
 * Mục đang chọn có thuộc phần `part` của kết quả v3 không. Khoá của mục theo chỉ số (TopicBlock,
 * TaskAssignmentBlock, DecisionBlock, TaskProgressBlock, VerifierRecordsBlock), nên sau khi chạy
 * lại một phần, cùng khoá có thể trỏ sang mục khác.
 */
export function selectionBelongsToPart(part: V3Part, key: string): boolean {
  if (key.startsWith("verify:")) {
    return (part === "assignments" && key.includes(":action:")) || (part === "decisions" && key.includes(":decision:"));
  }
  if (key.startsWith("assignment:")) return part === "assignments";
  if (key.startsWith("decision:")) return part === "decisions";
  if (key.startsWith("progress:")) return part === "progress";
  return part === "development"; // luận điểm: `${segment_id}:${speakerIdx}:${pointIdx}`
}
