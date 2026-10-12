import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, analyzeMeetingV3, getMeetingV3Analysis, reloadMeetingV3Part } from "../api/client";
import type { AnalyzeV3Request, AnalyzeV3Result, V3Part } from "../api/types";
import type { AnalysisStatus } from "./useAnalysis";

export interface V3AnalysisState {
  status: AnalysisStatus;
  request: AnalyzeV3Request | null;
  data: AnalyzeV3Result | null;
  error: string | null;
  elapsedMs: number;
  /** Các phần đang chạy lại; kết quả cũ vẫn hiển thị trong lúc chờ. */
  reloading: Partial<Record<V3Part, boolean>>;
  /** Lỗi của lần chạy lại gần nhất theo phần (kết quả cũ được giữ). */
  partErrors: Partial<Record<V3Part, string>>;
}

const INITIAL_STATE: V3AnalysisState = {
  status: "idle",
  request: null,
  data: null,
  error: null,
  elapsedMs: 0,
  reloading: {},
  partErrors: {},
};

// Phiên đang xem nằm trong sessionStorage để tải lại trang (F5) không mất kết quả: có
// analysis_key thì lấy lại từ cache backend (không gọi LLM); chưa có (tải lại khi đang chạy)
// thì gửi lại request -- backend trả cache hoặc cho request chờ chung lần chạy đang dở.
const SESSION_KEY = "meeting-analysis.v3.session";

interface StoredSession {
  request: AnalyzeV3Request;
  analysisKey?: string;
}

function saveSession(session: StoredSession | null) {
  try {
    if (session) sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // Hết quota (transcript lớn) hoặc storage bị chặn: chỉ mất khả năng khôi phục khi tải lại trang.
  }
}

function loadSession(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as StoredSession) : null;
  } catch {
    return null;
  }
}

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : "Lỗi không xác định khi gọi API.";
}

/** Response của cùng bản phân tích chỉ thay bản đang hiển thị khi không cũ hơn (cache_version). */
function isNotOlder(next: AnalyzeV3Result, current: AnalyzeV3Result | null): boolean {
  return !current || next.analysis_key !== current.analysis_key || next.cache_version >= current.cache_version;
}

function omit<K extends string, V>(record: Partial<Record<K, V>>, key: K): Partial<Record<K, V>> {
  const next = { ...record };
  delete next[key];
  return next;
}

/**
 * Pipeline v3: một request chạy một mạch tới kết quả. Mục Verifier chưa chắc được trao
 * đổi feedback với agent trích xuất tới khi đồng thuận ngay trong backend. Backend cache kết
 * quả theo request: `reloadPart` tính lại riêng một phần (Diễn biến/Giao việc/Kết luận/Tiến độ)
 * trên cùng chủ đề, `run(request, { refresh: true })` tính lại tất cả.
 */
export function useV3Analysis() {
  // Có phiên cần khôi phục thì bắt đầu ở "running" (effect bên dưới lấy lại kết quả).
  const [state, setState] = useState<V3AnalysisState>(() => {
    const session = loadSession();
    return session ? { ...INITIAL_STATE, status: "running", request: session.request } : INITIAL_STATE;
  });
  const timerRef = useRef<number | null>(null);
  // Bản sao đồng bộ của request/data đang hiển thị, để quyết định ngay khi response về (không
  // chờ setState) và để `reloadPart` không đọc phải closure cũ.
  const requestRef = useRef<AnalyzeV3Request | null>(null);
  const dataRef = useRef<AnalyzeV3Result | null>(null);
  // Tăng mỗi lần run/reset: response của lần chạy trước (kể cả chạy lại một phần) bị bỏ qua.
  const runIdRef = useRef(0);
  const restoredRef = useRef(false);

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Gửi request phân tích của lần chạy `runId` (state đã ở "running"); response của lần chạy cũ
  // hơn bị bỏ.
  const execute = useCallback(
    async (request: AnalyzeV3Request, options: { refresh?: boolean }, runId: number) => {
      const startedAt = Date.now();
      timerRef.current = window.setInterval(() => {
        setState((prev) => (prev.status === "running" ? { ...prev, elapsedMs: Date.now() - startedAt } : prev));
      }, 250);

      try {
        const data = await analyzeMeetingV3(request, options);
        if (runId !== runIdRef.current) return;
        stopTimer();
        dataRef.current = data;
        saveSession({ request, analysisKey: data.analysis_key });
        setState({ ...INITIAL_STATE, status: "success", request, data, elapsedMs: Date.now() - startedAt });
      } catch (err) {
        if (runId !== runIdRef.current) return;
        stopTimer();
        setState({
          ...INITIAL_STATE,
          status: "error",
          request,
          error: errorMessage(err),
          elapsedMs: Date.now() - startedAt,
        });
      }
    },
    [stopTimer],
  );

  const run = useCallback(
    (request: AnalyzeV3Request, options: { refresh?: boolean } = {}) => {
      stopTimer();
      const runId = ++runIdRef.current;
      requestRef.current = request;
      dataRef.current = null;
      saveSession({ request });
      setState({ ...INITIAL_STATE, status: "running", request });
      return execute(request, options, runId);
    },
    [execute, stopTimer],
  );

  /** Chạy lại riêng `part`. Trả true nếu kết quả hiển thị đã được thay bằng response mới. */
  const reloadPart = useCallback(async (part: V3Part): Promise<boolean> => {
    const request = requestRef.current;
    if (!request || !dataRef.current) return false;
    const runId = runIdRef.current;
    setState((prev) => ({
      ...prev,
      reloading: { ...prev.reloading, [part]: true },
      partErrors: omit(prev.partErrors, part),
    }));
    try {
      const data = await reloadMeetingV3Part(part, request);
      if (runId !== runIdRef.current) return false;
      const applied = isNotOlder(data, dataRef.current);
      if (applied) {
        dataRef.current = data;
        saveSession({ request, analysisKey: data.analysis_key });
      }
      setState((prev) => ({
        ...prev,
        data: applied ? data : prev.data,
        reloading: omit(prev.reloading, part),
      }));
      return applied;
    } catch (err) {
      if (runId !== runIdRef.current) return false;
      setState((prev) => ({
        ...prev,
        reloading: omit(prev.reloading, part),
        partErrors: { ...prev.partErrors, [part]: errorMessage(err) },
      }));
      return false;
    }
  }, []);

  const reset = useCallback(() => {
    stopTimer();
    runIdRef.current++;
    requestRef.current = null;
    dataRef.current = null;
    saveSession(null);
    setState(INITIAL_STATE);
  }, [stopTimer]);

  // Khôi phục phiên sau khi tải lại trang (một lần; ref giữ qua lần mount kép của StrictMode).
  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    const session = loadSession();
    if (!session) return;
    const { request, analysisKey } = session;
    const runId = ++runIdRef.current;
    requestRef.current = request;
    if (!analysisKey) {
      // Tải lại trang khi đang chạy: gửi lại, backend trả cache hoặc chờ chung lần chạy đang dở.
      // `execute` chỉ setState sau await/trong timer (state "running" đã có từ lúc khởi tạo).
      // oxlint-disable-next-line react/set-state-in-effect
      void execute(request, {}, runId);
      return;
    }
    getMeetingV3Analysis(analysisKey)
      .then((data) => {
        if (runId !== runIdRef.current) return;
        dataRef.current = data;
        setState({ ...INITIAL_STATE, status: "success", request, data });
      })
      .catch(() => {
        if (runId !== runIdRef.current) return;
        // Cache không còn (đổi mã nguồn/model hoặc bị xoá): về màn nhập, không tự chạy lại LLM.
        requestRef.current = null;
        saveSession(null);
        setState(INITIAL_STATE);
      });
  }, [execute]);

  return { ...state, run, reloadPart, reset };
}
