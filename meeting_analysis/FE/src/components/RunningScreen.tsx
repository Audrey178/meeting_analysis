import { formatElapsed } from "../lib/format";

interface RunningScreenProps {
  elapsedMs: number;
  meetingId: string;
}

// The agentic pipeline is one synchronous request with no progress events, so
// the steps are listed for orientation only -- none is marked done/active.
const STEPS: [string, string][] = [
  ["Chuẩn bị", "Dựng lượt nói, cắt chủ đề, gán tiêu đề + tóm tắt"],
  ["Trích xuất", "Content / Action / Decision agent chạy song song theo từng chủ đề"],
  ["Evidence-Check", "Luật kiểm lượt chốt, người phụ trách, trạng thái tự khai"],
  ["Debate + Judge", "Chỉ các mục đáng ngờ: ủng hộ, phản biện, trọng tài"],
];

export function RunningScreen({ elapsedMs, meetingId }: RunningScreenProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-14">
      <div className="flex flex-col items-center gap-2">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-divider border-t-accent" />
        <h2 className="m-0 text-center text-[24px]">Đang phân tích {meetingId}</h2>
        <div className="font-heading text-[30px] leading-none font-extrabold tabular-nums">
          {formatElapsed(elapsedMs)}
        </div>
      </div>
      <ol className="m-0 grid w-full max-w-[640px] list-none grid-cols-1 gap-2 p-0 sm:grid-cols-2">
        {STEPS.map(([title, description], idx) => (
          <li key={title} className="flex gap-3 bg-surface p-3">
            <span className="font-heading text-[18px] leading-none font-extrabold text-accent">{idx + 1}</span>
            <span className="flex flex-col gap-0.5">
              <span className="font-heading text-[13px] font-extrabold">{title}</span>
              <span className="text-[12px] leading-snug text-neutral-700">{description}</span>
            </span>
          </li>
        ))}
      </ol>
      <p className="max-w-[56ch] text-center text-[12px] text-neutral-600">
        Một request đồng bộ, API không báo tiến độ từng bước -- trang chỉ biết khi nào xong. Cuộc họp dài với nhiều mục
        đáng ngờ có thể mất vài phút. Gọi LLM thật, có tính phí.
      </p>
    </div>
  );
}
