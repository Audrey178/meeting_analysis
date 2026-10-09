import type { ActionItemV3Out, ActorType, AssigneeRole } from "../api/types";

export const UNASSIGNED_LABEL = "Chưa rõ người phụ trách";

export interface AssigneeEntry {
  item: ActionItemV3Out;
  /** Role of THIS group's party in the item; undefined for v1 items (no assignees). */
  role?: AssigneeRole;
}

export interface AssigneeGroup {
  assignee: string;
  /** Person/organization when every entry agrees; undefined for v1 items and the unassigned bucket. */
  actorType?: ActorType;
  entries: AssigneeEntry[];
}

const groupKey = (name: string) => name.trim().normalize("NFC").toLowerCase();

// Grouping-by-actor moved here from the backend (was `group_action_items_by_actor`
// in src/agentic/_shared.py, removed in M6 -- see be/DESIGN.md). Groups by EXACT
// match only (normalized: NFC + trim + lowercase), never by substring/fuzzy match --
// a real bug found in ground-truth data once merged an item actually assigned to
// "Sơn" into the meeting's dominant speaker "Phạm Hồng Sơn" by matching on a shared
// substring. First-seen order is preserved, the "unassigned" bucket goes last (it is
// a warning, not a person).
//
// v3 items carry `assignees` (one task can go to several parties: chủ trì + phối hợp),
// so a task shows up under EVERY resolved party, tagged with that party's role.
// Unresolved parties (name null) land once per task in the "unassigned" bucket.
// Items without `assignees` (v1, or v3 with no actor) group by `actor`.
export function groupActionItemsByAssignee(items: ActionItemV3Out[]): AssigneeGroup[] {
  const order: string[] = [];
  const groups = new Map<string, AssigneeGroup>();

  function add(key: string, display: string, entry: AssigneeEntry, actorType?: ActorType) {
    let group = groups.get(key);
    if (!group) {
      group = { assignee: display, actorType, entries: [] };
      groups.set(key, group);
      order.push(key);
    }
    if (group.entries.some((existing) => existing.item === entry.item)) return;
    if (group.actorType !== actorType) group.actorType = undefined;
    group.entries.push(entry);
  }

  for (const item of items) {
    const assignees = item.assignees ?? [];
    if (assignees.length === 0) {
      const actor = (item.actor ?? "").trim();
      add(actor ? groupKey(actor) : "", actor || UNASSIGNED_LABEL, { item });
      continue;
    }
    for (const assignee of assignees) {
      if (assignee.name) add(groupKey(assignee.name), assignee.name, { item, role: assignee.role }, assignee.actor_type);
      else add("", UNASSIGNED_LABEL, { item, role: assignee.role });
    }
  }

  const sorted = [...order.filter((key) => key !== ""), ...order.filter((key) => key === "")];
  return sorted.map((key) => groups.get(key)!);
}

// Same convention as the backend's make_speaker_initials: first letter of the
// first and last word ("Phạm Hồng Sơn" -> "PS"); a parenthesised role is ignored.
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
