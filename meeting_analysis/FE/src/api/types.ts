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

export interface AnalyzeRequest {
  meeting_id?: string;
  revision_id?: string;
  /** YYYY-MM-DD; optional for agentic/v3 -- anchors deadline normalization ("tuần sau" -> date). */
  meeting_date?: string;
  items: TranscriptItem[];
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
  /** Turn the extractor agent cites as the assignment/conclusion, if any. */
  confirm_turn_id?: string | null;
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

export interface AnalyzeV3Result {
  meeting_id: string;
  revision_id: string;
  topics: TopicOut[];
  verified_assignments: ActionItemOut[];
  verified_decisions: DecisionOut[];
  turns: TurnOut[];
  failed_topics: { segment_id: string; agent: string; error: string }[];
  verification_records: VerificationRecordOut[];
  /** Extractor agents the Planner skipped (no assign/decide cue in the topic). */
  skipped_agents: { segment_id: string; agent: string }[];
}

// ----- MA-MRG (src/agentic_v2), job chạy nền: POST /meetings/mrg/jobs, GET /meetings/mrg/jobs/{id} -----
// Mirrors be/schemas.py (MrgJobRequest, MrgJobStatus) and be/services/mrg.py::serialize_result
// (SPEC MA-MRG mục 10). Keep in sync by hand.

export type PipelineKind = "agentic" | "mrg" | "v3";

export interface MrgOptions {
  exchange: boolean;
  reviewer: "feedback" | "select" | "none";
  realizer: boolean;
  acceptance_policy: "unconfirmed" | "strict";
}

export interface MrgJobRequest extends AnalyzeRequest {
  meeting_date: string; // YYYY-MM-DD
  chair?: string | null;
  participants?: string[];
  options: MrgOptions;
}

/** Một bước truy vết: trường output này đến từ Act nào, ở turn nào, span nào, theo luật nào. */
export interface TraceStep {
  act_id: string;
  turn_id: string;
  rule: string;
  span: [number, number] | null;
}

export type AssignmentStatus = "confirmed" | "unconfirmed" | "self_committed";

export interface MrgTask {
  task_id: string;
  task: string;
  deliverable: string | null;
  task_role: "lead" | "support";
  co_actors: { person: string; task_role: string }[];
  assigned_by: string | null;
  assignment_status: AssignmentStatus;
  deadline_raw: string | null;
  deadline_norm: string | null;
  deadline_precision: string;
  superseded: { field: string; raw: unknown; act_id: string }[];
  condition: string | null;
  addresses_issue: string | null;
  segments: string[];
  fold_trace: Record<string, TraceStep[]>;
  warnings: string[];
}

export interface MrgPerson {
  person: string;
  role: string | null;
  tasks: MrgTask[];
  ongoing: { task_id: string; task: string; progress: string; fold_trace: TraceStep[] }[];
}

export interface MrgGiaoViec {
  people: MrgPerson[];
  warnings: { task_id: string; task: string; status: string; message: string }[];
  notes: { task_id: string; task: string; status: string }[];
}

interface MrgIssueBase {
  issue_id: string;
  issue: string;
  fold_trace: TraceStep[];
}

export interface MrgKetLuan {
  resolved: (MrgIssueBase & { conclusion: string | null; decided_by: string | null; basis: string[]; spawned_tasks: string[] })[];
  resolved_conditional: (MrgIssueBase & { conclusion: string | null; condition: string; follow_up: string[]; basis: string[] })[];
  deferred: (MrgIssueBase & { until: string | null })[];
  open: (MrgIssueBase & { alternatives: string[]; follow_up: string[]; owner_missing: boolean })[];
  warnings: { anomaly_id: string; message: string }[];
}

export interface MrgThreadTurn {
  act_id: string;
  act_type: string;
  speaker: string;
  speaker_source: "inferred" | "asr" | "unreliable";
  content: string;
  evidence: { turn_id: string; span: [number, number] | null }[];
}

export interface MrgThread {
  thread_id: string;
  segment_id: string;
  kind: "report_qa" | "proposal_debate" | "assignment" | "other";
  turns: MrgThreadTurn[];
  outcome: { issue_id: string | null; task_ids: string[] };
  narrative: string;
}

export interface MrgSegmentThreads {
  segment_id: string;
  title: string;
  threads: MrgThread[];
}

export interface MrgTurn extends TurnOut {
  segment_id: string;
  merged_suspect: boolean;
}

export interface MrgWarning {
  rule: string;
  message: string;
  anomaly_id?: string;
}

export interface MrgResult {
  meeting_id: string;
  revision_id: string;
  meeting_date: string;
  chair: string | null;
  turns: MrgTurn[];
  segments: { segment_id: string; order: number; title: string; summary: string }[];
  giao_viec: MrgGiaoViec;
  ket_luan: MrgKetLuan;
  dien_bien: MrgSegmentThreads[];
  thong_bao: string | null;
  warnings: MrgWarning[];
  report: MrgReport;
}

export interface MrgStage2Round {
  round: number;
  kind?: string;
  active?: number;
  submitted: number;
  accepted: number;
  rejected?: number;
  conflicts?: number;
  new_anomalies?: number;
}

export interface MrgReviewDecision {
  conflict_id: string;
  kind: string;
  target: string;
  winner: string | null;
  runner_up: string | null;
  margin: number | null;
  warning: string | null;
  totals: Record<string, number>;
}

export interface MrgReport {
  kb_version: string;
  prompt_versions: Record<string, string>;
  config: Record<string, unknown>;
  stage1: {
    proposed: number;
    kept: number;
    by_status: Record<string, number>;
    drop_rate: number;
    ambiguous_rate: number;
    fuzzy_rate: number;
    acts: number;
    failed_branches: string[];
  };
  stage2: { rounds: MrgStage2Round[]; messages: number; accepted: number; rejected: number; conflicts: number };
  stage3: {
    decisions: MrgReviewDecision[];
    feedback: { feedback_id: string; to: string; about: string; issue: string; rule: string }[];
    feedback_round: { round: number; owners: string[]; accepted: number } | null;
  };
  anomalies: Record<string, number>;
  consistency_violations: string[];
  tasks: number;
  issues: number;
  threads: number;
}

export interface MrgJobStatus {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string;
  stage_label: string;
  progress: Record<string, number | string>;
  error: string | null;
  elapsed_s: number;
  result: MrgResult | null;
}

/** Một đoạn bằng chứng để tô trên transcript: turn + (tùy chọn) span ký tự trong turn. */
export interface EvidenceRef {
  turn_id: string;
  span: [number, number] | null;
}
