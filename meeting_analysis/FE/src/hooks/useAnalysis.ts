import { useCallback, useRef, useState } from "react";
import { ApiError, analyzeMeeting } from "../api/client";
import type { AnalyzeRequest, AnalyzeResponse } from "../api/types";

export type AnalysisStatus = "idle" | "running" | "success" | "error";

export interface AnalysisState {
  status: AnalysisStatus;
  request: AnalyzeRequest | null;
  data: AnalyzeResponse | null;
  error: string | null;
  elapsedMs: number;
}

const INITIAL_STATE: AnalysisState = {
  status: "idle",
  request: null,
  data: null,
  error: null,
  elapsedMs: 0,
};

export function useAnalysis() {
  const [state, setState] = useState<AnalysisState>(INITIAL_STATE);
  const timerRef = useRef<number | null>(null);

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const run = useCallback(
    async (request: AnalyzeRequest) => {
      stopTimer();
      const startedAt = Date.now();
      setState({ status: "running", request, data: null, error: null, elapsedMs: 0 });
      timerRef.current = window.setInterval(() => {
        setState((prev) =>
          prev.status === "running" ? { ...prev, elapsedMs: Date.now() - startedAt } : prev,
        );
      }, 250);

      try {
        const data = await analyzeMeeting(request);
        stopTimer();
        setState({
          status: "success",
          request,
          data,
          error: null,
          elapsedMs: Date.now() - startedAt,
        });
      } catch (err) {
        stopTimer();
        const message =
          err instanceof ApiError ? err.message : "Lỗi không xác định khi gọi API.";
        setState({
          status: "error",
          request,
          data: null,
          error: message,
          elapsedMs: Date.now() - startedAt,
        });
      }
    },
    [stopTimer],
  );

  const reset = useCallback(() => {
    stopTimer();
    setState(INITIAL_STATE);
  }, [stopTimer]);

  return { ...state, run, reset };
}
