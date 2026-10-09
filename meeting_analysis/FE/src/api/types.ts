// Mirrors be/api.py's pydantic schemas.
// Keep these two files in sync by hand — there's no shared schema source yet.

export interface TranscriptItem {
  id: string;
  text: string;
  speaker?: string | null;
  speaker_role?: string | null;
  start_ms?: number | null;
  end_ms?: number | null;
  [key: string]: unknown;
}

/** Danh sách người/đơn vị tham dự (cùng dạng file `<transcript>.attendees.json`); chỉ v3 dùng. */
export interface AttendeesIn {
  people: { id: string; full_name: string; position?: string; org_id?: string | null }[];
  organizations: { id: string; name: string; functions?: string[]; aliases?: string[] }[];
}

export interface AnalyzeRequest {
  meeting_id?: string;
  revision_id?: string;
  /** YYYY-MM-DD; optional for agentic/v3 -- anchors deadline normalization ("tuần sau" -> date). */
  meeting_date?: string;
  items: TranscriptItem[];
  /** v3 only: lets the backend resolve actors to listed people/organizations. */
  attendees?: AttendeesIn;
}

export interface SpeakerPointOut {
  text: string;
  evidence_ids: string[];
  quotes: string[];
  citation_count: number;
}

export interface SpeakerSectionOut {
  initials: string;
  full_name: string;
  points: SpeakerPointOut[];
}

export interface TopicOut {
  segment_id: string;
  title: string;
  summary: string;
  speakers: SpeakerSectionOut[];
}

// Verified (post Evidence-Check, + Debate/Judge if it was uncertain) action
// item. `actor` rides on EACH item now -- the backend no longer groups these
// by person (that was `group_task_assignments`, removed in M6); grouping for
// display, if wanted, is a frontend concern now (see TaskAssignmentBlock.tsx).
/** How a verified item got into the result: rule CLEAR, Debate+Judge, or kept by the safety fallback. */
/** v3 adds "consensus" (Verifier and extractor agreed) and "verifier" (no agreement, Verifier's last ruling). */
export type Verification = "rule" | "debate" | "fallback" | "consensus" | "verifier";

export interface ActionItemOut {
  segment_id: string;
  actor: string | null;
  /** Task content only -- never repeats "giao <actor>" or the deadline. */
  text: string;
  /** Deadline exactly as said in the transcript ("trước ngày 15 tháng 11"). */
  deadline_raw?: string | null;
  /** deadline_raw resolved against the meeting date (ISO "YYYY-MM-DD"), null if unresolvable. */
  deadline_date?: string | null;
  deadline_kind?: "exact" | "before" | "end_of_period" | "relative" | "unknown";
  status?: "assigned" | "self_committed" | "proposed" | "reported" | "unknown";
  /** Turn where the task was assigned/accepted (also part of evidence_ids). */
  confirm_turn_id?: string | null;
  verification?: Verification;
  evidence_ids: string[];
  quotes: string[];
  citation_count: number;
}

// Verified decision/chốt phương án. No synthesized administrative paragraph
// any more (that was `conclusion_agent`, an LLM step, removed in M6) -- this
// is the flat, unmerged list of confirmed decisions.
export interface DecisionOut {
  segment_id: string;
  text: string;
  status?: "agreed" | "proposed" | "reported" | "unknown";
  confirm_turn_id?: string | null;
  verification?: Verification;
  evidence_ids: string[];
  quotes: string[];
  citation_count: number;
}

export interface DebateRecordOut {
  segment_id: string;
  kind: "action" | "decision";
  candidate_text: string;
  reasons: string[];
  support_argument: string;
  oppose_argument: string;
  kept: boolean;
  reasoning: string;
  /** keep / revise (actor corrected) / drop. */
  verdict?: "keep" | "revise" | "drop";
  /** Candidate after the judge's correction ("" when dropped). */
  final_text?: string;
  /** Turn the judge relied on (assignment/confirmation), if any. */
  deciding_turn_id?: string | null;
}

export interface TurnOut {
  turn_id: string;
  speaker: string | null;
  text: string;
}

export interface AnalyzeResponse {
  meeting_id: string;
  revision_id: string;
  topics: TopicOut[];
  verified_assignments: ActionItemOut[];
  verified_decisions: DecisionOut[];
  turns: TurnOut[];
  /** Per-topic LLM calls still failing after retries; that topic's output is missing. */
  failed_topics?: { segment_id: string; agent: string; error: string }[];
  /** Candidates that Evidence-Check flagged uncertain and Debate+Judge ruled on. */
  debate_records?: DebateRecordOut[];
}

// ----- Agentic v3 (src/agentic_v3): POST /v3/meetings/analyze -> AnalyzeV3Result -----
// Mirrors be/schemas.py (AnalyzeV3Result & co). Keep in sync by hand.

export interface VerifierStepOut {
  thought: string;
  action: string;
  argument: string;
  observation: string;
}

/** One round: the Verifier sends feedback, the extractor agent answers. */
export interface ConsensusRoundOut {
  candidate_text: string;
  verdict: string;
  feedback: string;
  deciding_turn_id: string | null;
  /** "accept" | "amend" | "defend"; empty when the Verifier kept the candidate. */
  stance: string;
  response: string;
}

export interface VerificationRecordOut {
  item_key: string;
  segment_id: string;
  kind: "action" | "decision";
  candidate_text: string;
  reasons: string[];
  steps: VerifierStepOut[];
  /** keep / revise / drop, or "unresolved" when kept by the safety fallback. */
  verdict: string;
  reasoning: string;
  final_text: string;
  deciding_turn_id: string | null;
  decided_by: "consensus" | "verifier" | "fallback" | string;
  rounds: ConsensusRoundOut[];
}

export type ActorType = "person" | "organization" | "unknown";
/** lead = chủ trì / người nhận chính, support = phối hợp, joint = cùng thực hiện. */
export type AssigneeRole = "lead" | "support" | "joint";

export interface ActorCandidateOut {
  name: string;
  actor_type: ActorType;
  score: number;
  reason: string;
  ref_id: string | null;
}

/** One party receiving the task; `name` is null when unresolved (`flag` = "ambiguous"). */
export interface ActorAssigneeOut {
  mention: string;
  role: AssigneeRole;
  name: string | null;
  actor_type: ActorType;
  flag: string | null;
  reason: string;
  ref_id: string | null;
  candidates: ActorCandidateOut[];
}

/** v3 action item: v1 fields + actor identification. `actor` = every party's name joined by ", ". */
export interface ActionItemV3Out extends ActionItemOut {
  actor_type?: ActorType;
  /** "ambiguous" (some party unresolved) | "missing" (no actor at all). */
  actor_flag?: string | null;
  actor_reason?: string;
  actor_candidates?: ActorCandidateOut[];
  assignees?: ActorAssigneeOut[];
}

export interface AnalyzeV3Result {
  meeting_id: string;
  revision_id: string;
  topics: TopicOut[];
  verified_assignments: ActionItemV3Out[];
  verified_decisions: DecisionOut[];
  turns: TurnOut[];
  failed_topics: { segment_id: string; agent: string; error: string }[];
  verification_records: VerificationRecordOut[];
  /** Extractor agents the Planner skipped (no assign/decide cue in the topic). */
  skipped_agents: { segment_id: string; agent: string }[];
}

export type PipelineKind = "agentic" | "v3";

/** Một đoạn bằng chứng để tô trên transcript: turn + (tùy chọn) span ký tự trong turn. */
export interface EvidenceRef {
  turn_id: string;
  span: [number, number] | null;
}
