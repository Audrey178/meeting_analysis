import { useEffect, useMemo, useRef, useState } from "react";
import type { AttendeesIn, PipelineKind, TasksIn, TranscriptItem } from "../api/types";
import sampleTranscript from "../data/sample-transcript.json";

interface ParsedTranscript {
  meeting_id?: string;
  revision_id?: string;
  items: TranscriptItem[];
}

interface InputScreenProps {
  /**
   * ``meetingDate`` is "" when left empty. ``chair`` is "" when left empty or when the
   * pipeline does not use it (agentic v1). ``attendees`` and ``tasks`` are v3-only.
   */
  onStart: (
    transcript: ParsedTranscript,
    pipeline: PipelineKind,
    meetingDate: string,
    chair: string,
    attendees: AttendeesIn | null,
    tasks: TasksIn | null,
  ) => void;
  /** Called whenever the pasted JSON parses (or stops parsing), for the transcript preview. */
  onPreview?: (items: TranscriptItem[] | null) => void;
}

function todayIso(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

// STT export dùng speaker_name, dạng native dùng speaker.
function speakerOf(item: TranscriptItem): string | null {
  const value = item.speaker ?? (item.speaker_name as string | undefined) ?? null;
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function tryParse(text: string): {
  parsed: ParsedTranscript | null;
  error: string | null;
} {
  if (!text.trim()) return { parsed: null, error: null };
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    return {
      parsed: null,
      error: err instanceof Error ? err.message : "JSON không hợp lệ.",
    };
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return {
      parsed: null,
      error: "JSON gốc phải là một object { meeting_id, revision_id, items }.",
    };
  }
  const obj = raw as Record<string, unknown>;
  if (!Array.isArray(obj.items)) {
    return { parsed: null, error: "Thiếu trường items (mảng)." };
  }
  return {
    parsed: {
      meeting_id: typeof obj.meeting_id === "string" ? obj.meeting_id : undefined,
      revision_id: typeof obj.revision_id === "string" ? obj.revision_id : undefined,
      items: obj.items as TranscriptItem[],
    },
    error: null,
  };
}

// Danh sách tham dự cho v3, cùng dạng file `<transcript>.attendees.json`.
function parseAttendees(text: string): { attendees: AttendeesIn | null; error: string | null } {
  if (!text.trim()) return { attendees: null, error: null };
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    return { attendees: null, error: err instanceof Error ? err.message : "JSON không hợp lệ." };
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return { attendees: null, error: "Phải là object { people, organizations }." };
  }
  const obj = raw as Record<string, unknown>;
  const people = obj.people ?? [];
  const organizations = obj.organizations ?? [];
  if (!Array.isArray(people) || !Array.isArray(organizations)) {
    return { attendees: null, error: "people và organizations phải là mảng." };
  }
  const badPerson = people.find((p) => typeof p?.id !== "string" || typeof p?.full_name !== "string");
  if (badPerson) return { attendees: null, error: "Mỗi người cần id và full_name." };
  const badOrg = organizations.find((o) => typeof o?.id !== "string" || typeof o?.name !== "string");
  if (badOrg) return { attendees: null, error: "Mỗi đơn vị cần id và name." };
  const badAliases = organizations.find(
    (o) => o.aliases !== undefined && (!Array.isArray(o.aliases) || o.aliases.some((a: unknown) => typeof a !== "string")),
  );
  if (badAliases) return { attendees: null, error: `aliases của "${badAliases.name}" phải là mảng chuỗi.` };
  return { attendees: { people, organizations } as AttendeesIn, error: null };
}

const TASK_STATUSES = ["not_started", "in_progress", "done", "blocked"];

// Danh sách việc cần báo cáo tiến độ cho v3, cùng dạng file `<transcript>.tasks.json`.
// Mã người/đơn vị (P*/O*) được backend tra trong danh sách tham dự (sai thì 422).
function parseTasks(text: string): { tasks: TasksIn | null; error: string | null } {
  if (!text.trim()) return { tasks: null, error: null };
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (err) {
    return { tasks: null, error: err instanceof Error ? err.message : "JSON không hợp lệ." };
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return { tasks: null, error: "Phải là object { tasks }." };
  }
  const tasks = (raw as Record<string, unknown>).tasks;
  if (!Array.isArray(tasks)) return { tasks: null, error: "tasks phải là mảng." };
  for (const task of tasks) {
    if (typeof task?.id !== "string" || typeof task?.title !== "string" || typeof task?.owner !== "string") {
      return { tasks: null, error: "Mỗi việc cần id, title và owner (chuỗi)." };
    }
    if (task.support !== undefined && (!Array.isArray(task.support) || task.support.some((v: unknown) => typeof v !== "string"))) {
      return { tasks: null, error: `support của ${task.id} phải là mảng chuỗi.` };
    }
    if (task.due != null && !/^\d{4}-\d{2}-\d{2}$/.test(task.due)) {
      return { tasks: null, error: `due của ${task.id} phải là YYYY-MM-DD.` };
    }
    if (task.last_status != null && !TASK_STATUSES.includes(task.last_status)) {
      return { tasks: null, error: `last_status của ${task.id} phải là một trong ${TASK_STATUSES.join(", ")}.` };
    }
  }
  const ids = tasks.map((task) => task.id);
  if (new Set(ids).size !== ids.length) return { tasks: null, error: "Trùng mã việc." };
  return { tasks: { tasks } as TasksIn, error: null };
}

function computeStats(items: TranscriptItem[]) {
  const speakers = new Set(items.map(speakerOf).filter(Boolean));
  const starts = items
    .map((item) => item.start_ms)
    .filter((v): v is number => typeof v === "number");
  const ends = items
    .map((item) => item.end_ms)
    .filter((v): v is number => typeof v === "number");
  const durationS =
    starts.length && ends.length
      ? ((Math.max(...ends) - Math.min(...starts)) / 1000).toFixed(1)
      : null;
  return { itemCount: items.length, speakerCount: speakers.size, durationS };
}

export function InputScreen({ onStart, onPreview }: InputScreenProps) {
  const [text, setText] = useState(() =>
    JSON.stringify(sampleTranscript, null, 2),
  );
  const fileInputRef = useRef<HTMLInputElement>(null);
  const attendeesFileRef = useRef<HTMLInputElement>(null);
  const [attendeesText, setAttendeesText] = useState("");
  const { attendees, error: attendeesError } = useMemo(() => parseAttendees(attendeesText), [attendeesText]);
  const tasksFileRef = useRef<HTMLInputElement>(null);
  const [tasksText, setTasksText] = useState("");
  const { tasks, error: tasksError } = useMemo(() => parseTasks(tasksText), [tasksText]);

  const [pipeline, setPipeline] = useState<PipelineKind>("v3");
  const [meetingDate, setMeetingDate] = useState(todayIso);
  const [chair, setChair] = useState("");

  const { parsed, error } = useMemo(() => tryParse(text), [text]);
  const stats = parsed ? computeStats(parsed.items) : null;
  useEffect(() => {
    onPreview?.(parsed ? parsed.items : null);
  }, [parsed, onPreview]);
  const speakerNames = useMemo(
    () => (parsed ? [...new Set(parsed.items.map(speakerOf).filter((s): s is string => Boolean(s)))] : []),
    [parsed],
  );
  const meetingDateValid = /^\d{4}-\d{2}-\d{2}$/.test(meetingDate);
  const usesChair = pipeline === "v3";
  const canStart =
    Boolean(parsed && parsed.items.length > 0) &&
    (meetingDateValid || meetingDate === "") &&
    !(pipeline === "v3" && (attendeesError || tasksError));

  function start() {
    if (!parsed) return;
    onStart(
      parsed,
      pipeline,
      meetingDate,
      usesChair ? chair.trim() : "",
      pipeline === "v3" ? attendees : null,
      pipeline === "v3" && tasks && tasks.tasks.length > 0 ? tasks : null,
    );
  }

  function loadSample() {
    setText(JSON.stringify(sampleTranscript, null, 2));
  }

  async function handleFile(file: File) {
    setText(await file.text());
  }

  const PIPELINE_LABEL: Record<PipelineKind, string> = { agentic: "Agentic", v3: "Agentic v3" };

  const pipelines = [
    {
      value: "agentic" as const,
      label: "Agentic",
      badge: null,
      description: "Content / Action / Decision + Evidence-Check, mục đáng ngờ qua Debate+Judge. Một request đồng bộ.",
    },
    {
      value: "v3" as const,
      label: "Agentic v3",
      badge: "khuyên dùng",
      description:
        "Mọi chủ đề chạy song song, Planner bỏ agent thừa, Verifier tra cả cuộc họp và trao đổi với agent trích xuất tới khi đồng thuận; định danh actor là người/đơn vị theo danh sách tham dự.",
    },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 overflow-y-auto px-10 py-8">
        <div className="mx-auto flex w-full max-w-[720px] flex-col gap-8">
          <header>
            <h2 className="mb-1.5 text-[30px]">Phân tích cuộc họp</h2>
            <p className="m-0 max-w-[62ch] text-[14px] text-neutral-700">
              Nạp transcript ASR, chọn pipeline, nhận lại Diễn biến · Giao việc · Kết luận -- mỗi mục đều bấm được để xem
              lượt nói làm bằng chứng. Chưa có gì được gửi đi cho tới khi bạn bấm phân tích.
            </p>
          </header>

          <section>
            <StepHeading index={1} title="Transcript" />
            <div className="bg-surface p-4">
              <div className="field">
                <label>
                  JSON gốc -- cùng cấu trúc <code>inputs/sample_transcript.json</code> (hoặc STT export)
                </label>
                <textarea
                  className="input"
                  rows={9}
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  spellCheck={false}
                />
              </div>
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <button type="button" className="btn btn-secondary" onClick={() => fileInputRef.current?.click()}>
                  Chọn tệp .json
                </button>
                <button type="button" className="btn btn-ghost" onClick={loadSample}>
                  Dùng transcript mẫu
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/json"
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void handleFile(file);
                    event.target.value = "";
                  }}
                />
                {error && <span className="ml-auto text-[12.5px] text-accent-700">JSON lỗi: {error}</span>}
                {!error && parsed && <span className="ml-auto text-[12px] text-ok">✓ đọc được -- xem trước ở cột trái</span>}
              </div>
              {stats && (
                <div className="mt-4 grid grid-cols-3 divide-x divide-divider border-t border-divider pt-3">
                  <Stat value={stats.itemCount} label="mục transcript" />
                  <Stat value={stats.speakerCount} label="người nói" />
                  <Stat value={stats.durationS ? formatSeconds(Number(stats.durationS)) : "—"} label="thời lượng" />
                </div>
              )}
            </div>
          </section>

          <section>
            <StepHeading index={2} title="Pipeline" />
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2" role="radiogroup">
              {pipelines.map((item) => {
                const active = pipeline === item.value;
                return (
                  <button
                    key={item.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setPipeline(item.value)}
                    className={`flex gap-3 border-2 p-4 text-left transition-colors ${
                      active ? "border-accent bg-accent-100" : "border-transparent bg-surface hover:border-divider"
                    }`}
                  >
                    <span
                      className={`mt-0.5 flex h-4 w-4 flex-none items-center justify-center rounded-full border-2 ${
                        active ? "border-accent" : "border-neutral-500"
                      }`}
                    >
                      {active && <span className="h-2 w-2 rounded-full bg-accent" />}
                    </span>
                    <span className="flex flex-col gap-1">
                      <span className="flex items-center gap-2">
                        <span className="font-heading text-[15px] font-extrabold">{item.label}</span>
                        {item.badge && <span className="tag tag-ok !py-0">{item.badge}</span>}
                      </span>
                      <span className="text-[12.5px] leading-snug text-neutral-700">{item.description}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section>
            <StepHeading index={3} title="Thông tin cuộc họp" />
            <div className="flex flex-col gap-4 bg-surface p-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="field">
                  <label>
                    Ngày họp · tuỳ chọn, để quy thời hạn (“tuần sau”) ra ngày
                  </label>
                  <input
                    className="input"
                    type="date"
                    value={meetingDate}
                    onChange={(event) => setMeetingDate(event.target.value)}
                  />
                </div>
                {usesChair && (
                  <div className="field">
                    <label>Chủ trì · tuỳ chọn, giúp nhận ra lời giao việc/kết luận</label>
                    <input
                      className="input"
                      list="speaker-names"
                      value={chair}
                      placeholder={speakerNames[0] ? `vd ${speakerNames[0]}` : "vd Nguyễn Văn Hùng"}
                      onChange={(event) => setChair(event.target.value)}
                    />
                    <datalist id="speaker-names">
                      {speakerNames.map((name) => (
                        <option key={name} value={name} />
                      ))}
                    </datalist>
                  </div>
                )}
              </div>
              {pipeline === "v3" && (
                <div className="field">
                  <label>
                    Danh sách tham dự · tuỳ chọn -- JSON <code>{"{ people, organizations }"}</code> (tệp{" "}
                    <code>*.attendees.json</code>) để quy người giao việc về đúng người/đơn vị
                  </label>
                  <textarea
                    className="input !min-h-[60px]"
                    rows={4}
                    value={attendeesText}
                    placeholder='{"people": [{"id": "P1", "full_name": "...", "position": "...", "org_id": "O1"}], "organizations": [{"id": "O1", "name": "...", "aliases": ["..."], "functions": ["..."]}]}'
                    onChange={(event) => setAttendeesText(event.target.value)}
                    spellCheck={false}
                  />
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <button type="button" className="btn btn-secondary" onClick={() => attendeesFileRef.current?.click()}>
                      Chọn tệp danh sách
                    </button>
                    {attendeesText && (
                      <button type="button" className="btn btn-ghost" onClick={() => setAttendeesText("")}>
                        Bỏ danh sách
                      </button>
                    )}
                    <input
                      ref={attendeesFileRef}
                      type="file"
                      accept="application/json"
                      className="hidden"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void file.text().then(setAttendeesText);
                        event.target.value = "";
                      }}
                    />
                    {attendeesError && <span className="ml-auto text-[12.5px] text-accent-700">Lỗi: {attendeesError}</span>}
                    {attendees && (
                      <span className="ml-auto text-[12px] text-ok">
                        ✓ {attendees.people.length} người · {attendees.organizations.length} đơn vị
                        {(() => {
                          const aliasCount = attendees.organizations.reduce((sum, o) => sum + (o.aliases?.length ?? 0), 0);
                          return aliasCount > 0 ? ` · ${aliasCount} tên gọi tắt` : "";
                        })()}
                      </span>
                    )}
                  </div>
                </div>
              )}
              {pipeline === "v3" && (
                <div className="field">
                  <label>
                    Việc cần báo cáo tiến độ · tuỳ chọn -- JSON <code>{"{ tasks }"}</code> (tệp <code>*.tasks.json</code>);
                    owner/support là mã trong danh sách tham dự hoặc tên
                  </label>
                  <textarea
                    className="input !min-h-[60px]"
                    rows={4}
                    value={tasksText}
                    placeholder='{"tasks": [{"id": "T1", "title": "...", "owner": "O2", "support": ["O7"], "due": "2026-01-31", "last_status": "in_progress"}]}'
                    onChange={(event) => setTasksText(event.target.value)}
                    spellCheck={false}
                  />
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <button type="button" className="btn btn-secondary" onClick={() => tasksFileRef.current?.click()}>
                      Chọn tệp danh sách việc
                    </button>
                    {tasksText && (
                      <button type="button" className="btn btn-ghost" onClick={() => setTasksText("")}>
                        Bỏ danh sách việc
                      </button>
                    )}
                    <input
                      ref={tasksFileRef}
                      type="file"
                      accept="application/json"
                      className="hidden"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void file.text().then(setTasksText);
                        event.target.value = "";
                      }}
                    />
                    {tasksError && <span className="ml-auto text-[12.5px] text-accent-700">Lỗi: {tasksError}</span>}
                    {tasks && <span className="ml-auto text-[12px] text-ok">✓ {tasks.tasks.length} việc</span>}
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>

      <footer className="border-t-2 border-divider bg-bg px-10 py-3.5">
        <div className="mx-auto flex w-full max-w-[720px] items-center gap-4">
          <button type="button" className="btn btn-primary !px-6" disabled={!canStart} onClick={start}>
            Bắt đầu phân tích →
          </button>
          <span className="text-[12px] text-neutral-700">
            {parsed ? `${parsed.items.length} mục · ${PIPELINE_LABEL[pipeline]} · ` : ""}
            dùng API key thật, lần chạy này được tính phí.
          </span>
        </div>
      </footer>
    </div>
  );
}

function StepHeading({ index, title }: { index: number; title: string }) {
  return (
    <div className="mb-2.5 flex items-center gap-2.5">
      <span className="flex h-6 w-6 items-center justify-center bg-accent font-heading text-[12px] font-extrabold text-bg">
        {index}
      </span>
      <h3 className="m-0 text-[18px]">{title}</h3>
    </div>
  );
}

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="flex flex-col px-3 first:pl-0">
      <span className="font-heading text-[22px] leading-none font-extrabold">{value}</span>
      <span className="mt-1 text-[11.5px] text-neutral-700">{label}</span>
    </div>
  );
}

function formatSeconds(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  return minutes ? `${minutes}p ${String(seconds).padStart(2, "0")}s` : `${seconds}s`;
}
