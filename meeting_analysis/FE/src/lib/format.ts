import type { AssignmentTarget, Due, TaskOut } from "../api/types";

export const UNASSIGNED_LABEL = "Chưa rõ người phụ trách";

export type TargetKind = AssignmentTarget["target_type"];

/** Tên hiển thị của một bên nhận việc (đơn vị, người, hoặc cách gọi trong bản ghi khi chưa rõ). */
export function targetName(target: AssignmentTarget | null): string | null {
  if (!target) return null;
  if (target.target_type === "unit") return target.unit_name;
  if (target.target_type === "person") return target.person_name;
  return target.name;
}

/** Bên nhận việc chưa định danh được (resolver gắn cờ mơ hồ/thiếu). */
export function isUnresolved(target: AssignmentTarget | null): boolean {
  return !target || !targetName(target) || (target.target_type === "unknown" && Boolean(target.extensions.resolution?.flag));
}

export interface AssigneeEntry {
  task: TaskOut;
  target: AssignmentTarget | null;
  /** Vai của bên này trong việc: lead (chủ trì), support (phối hợp), joint (cùng thực hiện). */
  role: string;
}

export interface AssigneeGroup {
  assignee: string;
  /** Đơn vị/người khi mọi mục cùng loại; undefined với nhóm "chưa rõ". */
  kind?: TargetKind;
  entries: AssigneeEntry[];
}

const groupKey = (name: string) => name.trim().normalize("NFC").toLowerCase();

// Gom việc theo bên nhận việc. Chỉ gom khi tên KHỚP HẲN (chuẩn hoá NFC + trim + chữ thường), không
// gom theo chuỗi con/mờ -- từng gặp lỗi gom việc giao "Sơn" vào người nói "Phạm Hồng Sơn" vì trùng
// chuỗi con. Một việc có thể giao nhiều bên (chủ trì + phối hợp) nên hiện dưới MỌI bên đã định
// danh, kèm vai của bên đó; bên chưa định danh được vào nhóm "chưa rõ" (một lần mỗi việc), đặt
// cuối vì đó là cảnh báo, không phải một người. Giữ thứ tự xuất hiện đầu tiên.
export function groupTasksByAssignee(tasks: TaskOut[]): AssigneeGroup[] {
  const order: string[] = [];
  const groups = new Map<string, AssigneeGroup>();

  function add(key: string, display: string, entry: AssigneeEntry, kind?: TargetKind) {
    let group = groups.get(key);
    if (!group) {
      group = { assignee: display, kind, entries: [] };
      groups.set(key, group);
      order.push(key);
    }
    if (group.entries.some((existing) => existing.task === entry.task)) return;
    if (group.kind !== kind) group.kind = undefined;
    group.entries.push(entry);
  }

  for (const task of tasks) {
    const { primary, collaborators } = task.extracted.assignment;
    const targets = primary ? [primary, ...collaborators] : [null];
    targets.forEach((target, index) => {
      const role = target?.extensions.resolution?.role ?? (index === 0 ? "lead" : "support");
      const entry = { task, target, role };
      const name = targetName(target);
      if (isUnresolved(target) || !name) add("", UNASSIGNED_LABEL, entry);
      else add(groupKey(name), name, entry, target!.target_type);
    });
  }

  const sorted = [...order.filter((key) => key !== ""), ...order.filter((key) => key === "")];
  return sorted.map((key) => groups.get(key)!);
}

/** "2026-01-31" -> "31/01/2026". */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const [year, month, day] = iso.split("-");
  return day && month ? `${day}/${month}/${year}` : iso;
}

const DUE_KIND_PREFIX: Record<string, string> = { before: "trước ", end_of_period: "cuối kỳ · " };

/** "trước 15/11/2026" khi hạn quy được về ngày; không thì nguyên văn. */
export function formatDue(due: Due | null): string {
  if (!due) return "";
  if (!due.date) return due.raw ?? "";
  return `${DUE_KIND_PREFIX[due.kind] ?? ""}${formatDate(due.date)}`;
}

/** Số thứ tự chủ đề hai chữ số ("03"). */
export function topicNumber(index: number): string {
  return String(index + 1).padStart(2, "0");
}

// First letter of the first and last word ("Phạm Hồng Sơn" -> "PS"); a
// parenthesised role is ignored.
export function initialsOf(name: string): string {
  const words = name.replace(/\(.*?\)/g, "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = words[0][0] ?? "";
  const last = words.length > 1 ? (words[words.length - 1][0] ?? "") : "";
  return (first + last).toUpperCase();
}

export function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatDurationMs(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

// Muted categorical palette for speakers (readable with white initials, calm
// next to the red accent, which stays reserved for selection/warnings).
const SPEAKER_COLORS = ["#3d5a80", "#6b4e71", "#2e6b4f", "#8a5a2b", "#4a6670", "#7a4b4b", "#55607a", "#5e6b3a"];

const assignedColors = new Map<string, string>();

/**
 * Stable color per speaker name, so the same person has the same chip
 * everywhere. Assigned in first-seen order (the transcript renders first),
 * so the first 8 speakers of a meeting never share a color -- a hash would
 * collide for small groups. The role in parentheses is ignored, so
 * "Anh Tuấn (Giám đốc)" and an actor written "Anh Tuấn" match.
 */
export function speakerColor(name: string | null | undefined): string {
  const key = (name ?? "").replace(/\(.*?\)/g, "").trim().normalize("NFC").toLowerCase();
  if (!key) return "#7d7979";
  let color = assignedColors.get(key);
  if (!color) {
    color = SPEAKER_COLORS[assignedColors.size % SPEAKER_COLORS.length];
    assignedColors.set(key, color);
  }
  return color;
}

/** Display name without the parenthesised role ("Anh Tuấn (Giám đốc)" -> "Anh Tuấn"). */
export function speakerName(name: string): string {
  return name.replace(/\s*\(.*?\)\s*/g, " ").trim() || name;
}

/** Parenthesised role, if any ("Anh Tuấn (Giám đốc)" -> "Giám đốc"). */
export function speakerRole(name: string): string | null {
  const match = name.match(/\(([^)]*)\)/);
  return match ? match[1].trim() : null;
}
