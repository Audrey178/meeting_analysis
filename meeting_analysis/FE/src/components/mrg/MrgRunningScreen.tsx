import type { MrgJobStatus } from "../../api/types";
import { formatElapsed } from "../../lib/format";

const STEPS: [string, string][] = [
  ["prepare", "Dựng lượt nói, cắt và gán nhãn chủ đề"],
  ["stage1", "Stage 1 — 4 role agent trích Act"],
  ["stage2", "Stage 2 — trao đổi giữa các agent"],
  ["stage3", "Stage 3 — Reviewer phân xử"],
  ["stage4", "Stage 4 — fold và chiếu 3 output"],
];

function detail(stage: string, progress: Record<string, number | string>): string {
  if (stage === "prepare" && progress.segments) return `${progress.turns} lượt nói · ${progress.segments} đoạn`;
  if (stage === "stage1" && progress.total) return `${progress.done}/${progress.total} nhánh (đoạn × role)`;
  if (stage === "stage2" && progress.round !== undefined) {
    return Number(progress.round) === 0
      ? "vòng 0: rule hòa giải khác role"
      : `vòng ${progress.round}: ${progress.accepted ?? 0} thay đổi được nhận`;
  }
  return "";
}

interface MrgRunningScreenProps {
  job: MrgJobStatus | null;
  elapsedMs: number;
  meetingId: string;
}

// Tiến độ thật từ server (job.stage + job.progress), không phải thanh tiến độ giả.
export function MrgRunningScreen({ job, elapsedMs, meetingId }: MrgRunningScreenProps) {
  const current = job?.stage ?? "queued";
  const currentIdx = STEPS.findIndex(([stage]) => stage === current);
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 px-14">
      <h2 className="text-[26px]">Đang phân tích {meetingId} bằng MA-MRG</h2>
      <div className="font-heading text-[28px] font-extrabold">{formatElapsed(elapsedMs)}</div>
      <ol className="m-0 flex w-full max-w-[520px] list-none flex-col gap-1.5 p-0">
        {STEPS.map(([stage, label], idx) => {
          const state = currentIdx === -1 ? "todo" : idx < currentIdx ? "done" : idx === currentIdx ? "active" : "todo";
          return (
            <li
              key={stage}
              className={`flex items-center gap-3 border-l-2 px-3 py-2 text-[13.5px] ${
                state === "active"
                  ? "border-l-accent bg-accent-100"
                  : state === "done"
                    ? "border-l-neutral-500 text-neutral-700"
                    : "border-l-transparent text-neutral-500"
              }`}
            >
              <span className="w-4 text-center">
                {state === "done" ? "✓" : state === "active" ? (
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-divider border-t-accent" />
                ) : "·"}
              </span>
              <span className="flex-1">{label}</span>
              {state === "active" && job && <span className="text-[12px] text-neutral-700">{detail(stage, job.progress)}</span>}
            </li>
          );
        })}
      </ol>
      <p className="max-w-[52ch] text-center text-[12px] text-neutral-600">
        {current === "queued" ? "Job đang chờ (server chạy lần lượt từng job). " : ""}
        Mỗi đoạn gọi 4 role agent, rồi tối đa 3 vòng trao đổi, thường mất vài phút. Gọi LLM thật, có tính phí; kết
        quả được cache nên chạy lại cùng transcript sẽ nhanh hơn.
      </p>
    </div>
  );
}
