import { useEffect, useMemo, useRef, useState } from "react";
import type { MrgOptions, PipelineKind, TranscriptItem } from "../api/types";
import sampleTranscript from "../data/sample-transcript.json";

interface ParsedTranscript {
  meeting_id?: string;
  revision_id?: string;
  items: TranscriptItem[];
}

export interface MrgSettings {
  meeting_date: string;
  chair: string | null;
  participants: string[];
  options: MrgOptions;
}

interface InputScreenProps {
  /**
   * ``meetingDate`` is "" when left empty (only allowed for agentic/v3); ``chair`` is "" when
   * left empty or when the pipeline does not use it (agentic v1).
   */
  onStart: (
    transcript: ParsedTranscript,
    pipeline: PipelineKind,
    meetingDate: string,
    chair: string,
    mrg: MrgSettings | null,
  ) => void;
  /** Called whenever the pasted JSON parses (or stops parsing), for the transcript preview. */
  onPreview?: (items: TranscriptItem[] | null) => void;
}

const DEFAULT_MRG_OPTIONS: MrgOptions = {
  exchange: true,
  reviewer: "feedback",
  realizer: true,
  acceptance_policy: "unconfirmed",
};

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

  const [pipeline, setPipeline] = useState<PipelineKind>("mrg");
  const [meetingDate, setMeetingDate] = useState(todayIso);
  const [chair, setChair] = useState("");
  const [participantsText, setParticipantsText] = useState("");
  const [options, setOptions] = useState<MrgOptions>(DEFAULT_MRG_OPTIONS);

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
  const usesChair = pipeline === "mrg" || pipeline === "v3";
  const canStart =
    Boolean(parsed && parsed.items.length > 0) && (meetingDateValid || (pipeline !== "mrg" && meetingDate === ""));

  function start() {
    if (!parsed) return;
    const chairName = usesChair ? chair.trim() : "";
    if (pipeline !== "mrg") {
      onStart(parsed, pipeline, meetingDate, chairName, null);
      return;
    }
    const participants = participantsText
      .split(/[\n,;]/)
      .map((name) => name.trim())
      .filter(Boolean);
    onStart(parsed, pipeline, meetingDate, chairName, {
      meeting_date: meetingDate,
      chair: chairName || null,
      participants,
      options,
    });
  }

  function loadSample() {
    setText(JSON.stringify(sampleTranscript, null, 2));
  }

  async function handleFile(file: File) {
    setText(await file.text());
  }

  const PIPELINE_LABEL: Record<PipelineKind, string> = { mrg: "MA-MRG", agentic: "Agentic", v3: "Agentic v3" };

  const pipelines = [
    {
      value: "mrg" as const,
      label: "MA-MRG",
      badge: "khuyên dùng",
      description: "4 agent theo vai trò + trao đổi + Reviewer. Giao việc/Kết luận suy bằng luật, mọi trường có truy vết.",
    },
    {
      value: "agentic" as const,
      label: "Agentic",
      badge: null,
      description: "Content / Action / Decision + Evidence-Check, mục đáng ngờ qua Debate+Judge. Một request đồng bộ.",
    },
    {
      value: "v3" as const,
      label: "Agentic v3",
      badge: "thử nghiệm",
      description:
        "Mọi chủ đề chạy song song, Planner bỏ agent thừa, Verifier tra cả cuộc họp; mục chưa chắc được Verifier và agent trích xuất trao đổi tới khi đồng thuận. Một request đồng bộ.",
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
                  JSON gốc -- cùng cấu trúc <code>run_to_TreeSeg.py --input</code> (hoặc STT export)
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
                    {pipeline === "mrg"
                      ? "Ngày họp · bắt buộc, dùng để chuẩn hoá thời hạn"
                      : "Ngày họp · tuỳ chọn, để quy thời hạn (“tuần sau”) ra ngày"}
                  </label>
                  <input
                    className="input"
                    type="date"
                    value={meetingDate}
                    required={pipeline === "mrg"}
                    onChange={(event) => setMeetingDate(event.target.value)}
                  />
                  {pipeline === "mrg" && !meetingDateValid && (
                    <span className="text-[12px] text-accent-700">MA-MRG cần ngày họp.</span>
                  )}
                </div>
                {usesChair && (
                  <div className="field">
                    <label>
                      {pipeline === "mrg"
                        ? "Chủ trì · để trống nếu chưa rõ"
                        : "Chủ trì · tuỳ chọn, giúp nhận ra lời giao việc/kết luận"}
                    </label>
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
              {pipeline === "mrg" && (
                <>
                  <div className="field">
                    <label>Thành viên · mỗi dòng hoặc dấu phẩy một người; trống = lấy người nói từ ASR</label>
                    <textarea
                      className="input !min-h-[60px] !font-[inherit] !text-[13.5px]"
                      rows={2}
                      value={participantsText}
                      placeholder={speakerNames.join(", ")}
                      onChange={(event) => setParticipantsText(event.target.value)}
                    />
                  </div>
                  <details className="group border-t border-divider pt-3">
                    <summary className="cursor-pointer font-heading text-[12px] font-extrabold tracking-[0.06em] text-neutral-700 uppercase select-none">
                      Tuỳ chọn nâng cao
                    </summary>
                    <div className="mt-3 grid grid-cols-1 gap-3 text-[13px] sm:grid-cols-2">
                      <label className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={options.exchange}
                          onChange={(event) => setOptions({ ...options, exchange: event.target.checked })}
                        />
                        Stage 2: trao đổi giữa các agent
                      </label>
                      <label className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={options.realizer}
                          onChange={(event) => setOptions({ ...options, realizer: event.target.checked })}
                        />
                        Realizer (Diễn biến + Thông báo)
                      </label>
                      <div className="field">
                        <label>Reviewer</label>
                        <select
                          className="input"
                          value={options.reviewer}
                          onChange={(event) =>
                            setOptions({ ...options, reviewer: event.target.value as MrgOptions["reviewer"] })
                          }
                        >
                          <option value="feedback">Phân xử + feedback</option>
                          <option value="select">Chỉ phân xử</option>
                          <option value="none">Tắt</option>
                        </select>
                      </div>
                      <div className="field">
                        <label>Chỉ đạo chưa có người đáp</label>
                        <select
                          className="input"
                          value={options.acceptance_policy}
                          onChange={(event) =>
                            setOptions({
                              ...options,
                              acceptance_policy: event.target.value as MrgOptions["acceptance_policy"],
                            })
                          }
                        >
                          <option value="unconfirmed">Vẫn tính là giao (gắn cờ)</option>
                          <option value="strict">Chưa tính là giao</option>
                        </select>
                      </div>
                    </div>
                  </details>
                </>
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
