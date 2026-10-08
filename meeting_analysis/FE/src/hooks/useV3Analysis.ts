import { useCallback, useRef, useState } from "react";
import { ApiError, analyzeMeetingV3 } from "../api/client";
import type { AnalyzeRequest, AnalyzeV3Result } from "../api/types";
import type { AnalysisStatus } from "./useAnalysis";

export interface V3AnalysisState {
  status: AnalysisStatus;
  request: AnalyzeRequest | null;
  data: AnalyzeV3Result | null;
  error: string | null;
  elapsedMs: number;
}

const INITIAL_STATE: V3AnalysisState = {
  status: "idle",
  request: null,
  data: null,
  error: null,
  elapsedMs: 0,
};

/**
 * Pipeline v3: một request chạy một mạch tới kết quả. Mục Verifier chưa chắc được trao
 * đổi feedback với agent trích xuất tới khi đồng thuận ngay trong backend.
 */
export function useV3Analysis() {
  const [state, setState] = useState<V3AnalysisState>(INITIAL_STATE);
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
      setState({ ...INITIAL_STATE, status: "running", request });
      timerRef.current = window.setInterval(() => {
        setState((prev) => (prev.status === "running" ? { ...prev, elapsedMs: Date.now() - startedAt } : prev));
      }, 250);

      try {
        const data = await analyzeMeetingV3(request);
        stopTimer();
        setState({ status: "success", request, data, error: null, elapsedMs: Date.now() - startedAt });
      } catch (err) {
        stopTimer();
        setState({
          status: "error",
          request,
          data: null,
          error: err instanceof ApiError ? err.message : "Lỗi không xác định khi gọi API.",
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
