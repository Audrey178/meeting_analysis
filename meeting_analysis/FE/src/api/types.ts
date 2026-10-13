// Mirrors be/schemas.py (request) and be/services/documents.py (three result documents).
// Keep these files in sync by hand — there's no shared schema source yet.

// ----- Request: POST /v3/meetings/{tasks|decisions|content} -----

export interface TranscriptItem {
  id: string | number;
  text?: string;
  speaker?: string | null;
  speaker_role?: string | null;
  start_ms?: number | null;
  end_ms?: number | null;
  [key: string]: unknown;
}

/** Danh sách người/đơn vị tham dự (cùng dạng file `<transcript>.attendees.json`). */
export interface AttendeesIn {
  people: { id: string; full_name: string; position?: string; org_id?: string | null }[];
  organizations: { id: string; name: string; functions?: string[]; aliases?: string[] }[];
}

export type TaskStatus = "not_started" | "in_progress" | "done" | "blocked";

/** Một việc cần báo cáo tiến độ (cùng dạng file `<transcript>.tasks.json`).
 * owner/support/reporter: mã người/đơn vị trong attendees (vd. "P1", "O2") hoặc tên tự do. */
export interface TaskIn {
  id: string;
  title: string;
  owner: string;
  support?: string[];
  reporter?: string | null;
  /** YYYY-MM-DD */
  due?: string | null;
  last_status?: TaskStatus | null;
  source?: string;
}

export interface TasksIn {
  tasks: TaskIn[];
}

export interface SourceIn {
  transcript_version_id?: string | null;
  transcript_uri?: string | null;
  document_uris?: string[];
}

export interface AnalyzeV3Request {
  meeting_id?: string;
  revision_id?: string;
  /** YYYY-MM-DD; neo để quy hạn tương đối ("tuần sau") về ngày, và `ngay_hop` của biên bản. */
  meeting_date?: string;
  items: TranscriptItem[];
  /** Quy actor về đúng người/đơn vị trong danh sách. */
  attendees?: AttendeesIn;
  /** Người chủ trì; đưa vào prompt để nhận ra lời giao việc/kết luận của chủ trì. */
  chair?: string | null;
  /** Việc cần báo cáo tiến độ; chỉ document Giao việc dùng. */
  tasks?: TasksIn;
  source?: SourceIn;
}

// ----- Khung chung của ba document -----

export type DocumentKind = "content" | "decisions" | "tasks";

/** Mã item transcript gốc (số khi xuất từ STT). */
export type ItemId = string | number;

export interface SegmentRef {
  segment_id: ItemId;
  turn_id: string;
  text: string;
  /** Mã người nói của item (`speaker_id`, hoặc `ref_id` của bản xuất STT). */
  speaker_id: string | null;
}

export interface GenerationWarning {
  code: string;
  topic_id: string;
  agent: string;
  message: string;
}

export interface Generation {
  /** "partial": có chủ đề lỗi (xem `warnings`); request sau sẽ tính lại. */
  status: "complete" | "partial";
  generated_at: string;
  coverage: { is_complete: boolean; processed_segment_count: number; total_segment_count: number };
  warnings: GenerationWarning[];
  confidence: number | null;
}

export interface DocumentAudit {
  verification_records?: VerificationRecordOut[];
  failed_topics?: { segment_id: string; agent: string; error: string }[];
}

export interface DocumentExtensions {
  /** analysis_key: khoá của transcript (nền chung của ba document). */
  input_fingerprint: string;
  /** Tên mục cache: `GET /v3/meetings/analyses/{input_fingerprint}/{document_key}`. */
  document_key: string;
  model: string | null;
  citation_namespace: string;
  task_identity_strategy: string | null;
  /** Tăng sau mỗi lần ghi cache; response có số nhỏ hơn bản đang hiển thị là response cũ. */
  artifact_version_id: number;
  audit: DocumentAudit;
  [key: string]: unknown;
}

interface DocumentBase {
  schema_version: string;
  meeting_id: string;
  /** Lần tính thứ mấy của document (1 = lần đầu). */
  artifact_revision: number;
  source: SourceIn;
  generation: Generation;
  extensions: DocumentExtensions;
}

// ----- Giao việc -----

export interface AssignmentResolution {
  mention: string | null;
  /** lead = chủ trì / người nhận chính, support = phối hợp, joint = cùng thực hiện. */
  role: "lead" | "support" | "joint" | string;
  /** "ambiguous" | "missing" | null */
  flag: string | null;
  reason: string;
  candidates: { name: string; actor_type: string; score: number; reason: string; ref_id: string | null }[];
}

interface TargetBase {
  extensions: { resolution: AssignmentResolution | null };
}

export type AssignmentTarget =
  | (TargetBase & { target_type: "unit"; unit_id: string | null; unit_name: string | null })
  | (TargetBase & { target_type: "person"; person_id: string | null; person_name: string | null })
  | (TargetBase & { target_type: "unknown"; name: string | null });

export interface Due {
  raw: string | null;
  /** YYYY-MM-DD */
  date: string | null;
  kind: "exact" | "before" | "end_of_period" | "relative" | "unknown" | string;
}

export type UpdateStatus = "done" | "in_progress" | "blocked" | "returned" | "deferred" | "mentioned";

export interface ProgressStep {
  topic_id: string;
  status: UpdateStatus;
  status_turn_id: string | null;
  summary: string;
  blockers: string[];
  directive: string;
  due: Due | null;
  deadline_removed: boolean;
  /** Trạng thái agent khai, khi bị Decisions sửa/hạ. */
  proposed_status: string | null;
  /** "revised" | "uncertain" | "kept" | null */
  status_flag: string | null;
  /** "decisions" | "unchecked" | "rule" */
  verification: string;
  reason: string;
  p_directive: number | null;
  /** Cập nhật quyết định trạng thái của việc. */
  deciding: boolean;
  segment_ids: ItemId[];
  turn_ids: string[];
}

export interface TaskProgress {
  previous_status: string | null;
  /** UpdateStatus hoặc "not_reported". */
  status: string;
  previous_due: string | null;
  status_conflict: boolean;
  uncertain: boolean;
  overdue: boolean;
  summary: string;
  blockers: string[];
  directive: string;
  deadline_removed: boolean;
  updates: ProgressStep[];
}

/** v3 thêm "consensus" (Verifier và agent trích xuất đồng thuận) và "verifier" (theo Verifier). */
export type Verification = "rule" | "debate" | "fallback" | "consensus" | "verifier";

export interface ReferenceExtensions {
  source_event_id: string | null;
  /** turn_id của các lượt chứa item được trích. */
  evidence_ids: string[];
  source_segment_refs: SegmentRef[];
}

export interface TaskOut {
  task_id: string;
  source_uri: string | null;
  extracted: {
    content: { title: string; description: string };
    assignment: {
      primary: AssignmentTarget | null;
      collaborators: AssignmentTarget[];
      assigned_by_speaker_id: string | null;
    };
    due: Due | null;
    priority: string | null;
    detection: {
      /** explicit = giao/nhận rõ; inferred = đề xuất/báo cáo đã qua kiểm chứng; backlog = việc cũ. */
      mode: "explicit" | "inferred" | "backlog";
      clarity: "clear" | "unclear";
      review_hints: string[];
    };
    references: { segment_ids: ItemId[]; confidence: number | null; extensions: ReferenceExtensions };
    /** Chỉ có ở việc cũ (backlog). */
    progress: TaskProgress | null;
  };
  workflow: {
    review_status: string;
    execution_status: string;
    required_confirmations: string[];
    dependency_task_ids: string[];
    source_presence: "present" | "absent";
    [key: string]: unknown;
  };
  extensions: ReferenceExtensions & {
    topic_id: string | null;
    status: string | null;
    verification: Verification | string | null;
    confirm_turn_id: string | null;
    /** "new" | "follow_up" | "backlog"; null khi request không có `tasks`. */
    relation: "new" | "follow_up" | "backlog" | string | null;
    /** Việc cũ: lời giao lại ("reassign") / dời hạn ("reschedule") đã gộp vào. */
    merged_relations: string[];
    assigned_by_speaker: string | null;
  };
}

export interface TasksDocument extends DocumentBase {
  document_type: "meeting_tasks";
  data: { tasks: TaskOut[] };
}

// ----- Kết luận -----

export interface DecisionsHeader {
  ngay_hop: string;
  chu_tri: string;
  thanh_phan: string;
  so_nguoi_tham_gia: number | null;
  so_nguoi_co_mat: number | null;
  [key: string]: unknown;
}

export interface DecisionItem {
  so_thu_tu: number;
  noi_dung: string;
  segment_ids: ItemId[];
  original_segment_ids: ItemId[];
  turn_ids: string[];
  extensions: {
    decision_id: string;
    topic_id: string;
    status: string;
    verification: Verification | string;
    confirm_turn_id: string | null;
    source_segment_refs: SegmentRef[];
  };
}

export interface DecisionsDocument extends DocumentBase {
  document_type: "meeting_decisions";
  data: { header: DecisionsHeader; items: DecisionItem[] };
}

// ----- Diễn biến -----

export interface DiscussionPoint {
  point_id: string;
  text: string;
  /** Người nói của các lượt được trích, theo thứ tự lên tiếng. */
  speakers: string[];
  /** `speaker_ids[i]` là mã người nói của `speakers[i]`. */
  speaker_ids: (string | null)[];
  segment_ids: ItemId[];
  turn_ids: string[];
  source_segment_refs: SegmentRef[];
}

export interface ContentTopic {
  topic_id: string;
  order: number;
  extracted: {
    content: { title: string; summary: string };
    /** Item và lượt nói đầu/cuối của chủ đề. */
    span: { segment_ids: ItemId[]; turn_ids: string[] };
    discussion_points: DiscussionPoint[];
  };
  extensions: { segmentation_method: string | null; boundary_score: number | null };
}

export interface TranscriptTurn {
  turn_id: string;
  speaker: string | null;
  speaker_id: string | null;
  segment_ids: ItemId[];
  text: string;
}

export interface ContentDocument extends DocumentBase {
  document_type: "meeting_content";
  data: { topics: ContentTopic[]; turns: TranscriptTurn[] };
}

export interface DocumentOf {
  content: ContentDocument;
  decisions: DecisionsDocument;
  tasks: TasksDocument;
}

export type MeetingDocument = DocumentOf[DocumentKind];

// ----- Bản ghi Verifier (extensions.audit.verification_records) -----

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

/** Bằng chứng đang chọn để tô trên transcript: item (mức chính) và lượt nói (tô cả lượt khi không có item). */
export interface Citation {
  segmentIds: ItemId[];
  turnIds: string[];
}
