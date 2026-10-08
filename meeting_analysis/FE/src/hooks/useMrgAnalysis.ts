import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, createMrgJob, getMrgJob } from "../api/client";
import type { MrgJobRequest, MrgJobStatus, MrgResult } from "../api/types";
import type { AnalysisStatus } from "./useAnalysis";

const POLL_INTERVAL_MS = 1500;
// Một vài lỗi mạng tạm thời khi poll không nên làm hỏng cả lần chạy (job vẫn chạy phía server).
const MAX_CONSECUTIVE_POLL_ERRORS = 5;

export interface MrgAnalysisState {
  status: AnalysisStatus;
  request: MrgJobRequest | null;
  job: MrgJobStatus | null;
  data: MrgResult | null;
  error: string | null;
  elapsedMs: number;
}

const INITIAL_STATE: MrgAnalysisState = {
  status: "idle",
  request: null,
  job: null,
  data: null,
  error: null,
  elapsedMs: 0,
};

// MA-MRG chạy vài phút nên backend dùng job nền: tạo job rồi poll trạng thái (kèm stage + tiến độ thật),
// thay vì một request đồng bộ như pipeline agentic cũ (useAnalysis).
export function useMrgAnalysis() {
  const [state, setState] = useState<MrgAnalysisState>(INITIAL_STATE);
  const pollRef = useRef<number | null>(null);
  const tickRef = useRef<number | null>(null);
  const runIdRef = useRef(0);

  const stopTimers = useCallback(() => {
    if (pollRef.current !== null) window.clearTimeout(pollRef.current);
    if (tickRef.current !== null) window.clearInterval(tickRef.current);
    pollRef.current = null;
    tickRef.current = null;
  }, []);

  useEffect(() => stopTimers, [stopTimers]);

  const run = useCallback(
    async (request: MrgJobRequest) => {
      stopTimers();
      const runId = ++runIdRef.current;
      const startedAt = Date.now();
      setState({ status: "running", request, job: null, data: null, error: null, elapsedMs: 0 });
      tickRef.current = window.setInterval(() => {
        setState((prev) =>
          prev.status === "running" ? { ...prev, elapsedMs: Date.now() - startedAt } : prev,
        );
      }, 250);

      const fail = (message: string) => {
        stopTimers();
        setState((prev) => ({ ...prev, status: "error", error: message, elapsedMs: Date.now() - startedAt }));
      };

      let job: MrgJobStatus;
      try {
        job = await createMrgJob(request);
      } catch (err) {
        fail(err instanceof ApiError ? err.message : "Lỗi không xác định khi tạo job.");
        return;
      }
      if (runId !== runIdRef.current) return;
      setState((prev) => ({ ...prev, job }));

      let pollErrors = 0;
      const poll = async () => {
        if (runId !== runIdRef.current) return;
        try {
          const current = await getMrgJob(job.job_id);
          pollErrors = 0;
          if (runId !== runIdRef.current) return;
          if (current.status === "succeeded" && current.result) {
            stopTimers();
            setState({
              status: "success",
              request,
              job: current,
              data: current.result,
              error: null,
              elapsedMs: Date.now() - startedAt,
            });
            return;
          }
          if (current.status === "failed") {
            setState((prev) => ({ ...prev, job: current }));
            fail(current.error ?? "Job MA-MRG thất bại.");
            return;
          }
          setState((prev) => ({ ...prev, job: current }));
        } catch (err) {
          pollErrors += 1;
          if (pollErrors >= MAX_CONSECUTIVE_POLL_ERRORS || (err instanceof ApiError && err.status === 404)) {
            fail(err instanceof ApiError ? err.message : "Mất kết nối khi theo dõi job.");
            return;
          }
        }
        pollRef.current = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
      };
      pollRef.current = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
    },
    [stopTimers],
  );

  const reset = useCallback(() => {
    runIdRef.current += 1;
    stopTimers();
    setState(INITIAL_STATE);
  }, [stopTimers]);

  return { ...state, run, reset };
}
