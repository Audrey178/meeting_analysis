import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, analyzeDocument, getDocument, type AnalyzeOptions } from "../api/client";
import type { AnalyzeV3Request, DocumentKind, DocumentOf } from "../api/types";

export const DOCUMENT_KINDS: DocumentKind[] = ["content", "tasks", "decisions"];

export type AnalysisStatus = "idle" | "running" | "success" | "error";

/** Một document: bản đang hiển thị (giữ nguyên trong lúc tính lại), đang tải, lỗi lần gần nhất. */
export interface DocumentSlot<K extends DocumentKind> {
  data: DocumentOf[K] | null;
  loading: boolean;
  error: string | null;
}

export type DocumentSlots = { [K in DocumentKind]: DocumentSlot<K> };

interface State {
  request: AnalyzeV3Request | null;
  docs: DocumentSlots;
  elapsedMs: number;
}

const EMPTY_SLOT = { data: null, loading: false, error: null };
const EMPTY_DOCS: DocumentSlots = { content: EMPTY_SLOT, decisions: EMPTY_SLOT, tasks: EMPTY_SLOT };
const LOADING_DOCS: DocumentSlots = {
  content: { ...EMPTY_SLOT, loading: true },
  decisions: { ...EMPTY_SLOT, loading: true },
  tasks: { ...EMPTY_SLOT, loading: true },
};
const INITIAL_STATE: State = { request: null, docs: EMPTY_DOCS, elapsedMs: 0 };

// Phiên đang xem nằm trong sessionStorage để tải lại trang (F5) không mất kết quả: document đã
// có `document_key` thì lấy lại từ cache backend (không gọi LLM); chưa có (tải lại khi đang
// chạy) thì gửi lại request -- backend trả cache hoặc cho request chờ chung lần tính đang dở.
const SESSION_KEY = "meeting-analysis.v3.documents";

interface StoredSession {
  request: AnalyzeV3Request;
  analysisKey?: string;
  documentKeys?: Partial<Record<DocumentKind, string>>;
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

/** Response của cùng bản phân tích chỉ thay bản đang hiển thị khi không cũ hơn (`artifact_version_id`). */
function isNotOlder(next: DocumentOf[DocumentKind], current: DocumentOf[DocumentKind] | null): boolean {
  return (
    !current ||
    next.extensions.input_fingerprint !== current.extensions.input_fingerprint ||
    next.extensions.artifact_version_id >= current.extensions.artifact_version_id
  );
}

/** Trạng thái chung: đang chạy khi chưa document nào có kết quả mà còn document đang tải. */
export function analysisStatus(request: AnalyzeV3Request | null, docs: DocumentSlots): AnalysisStatus {
  if (!request) return "idle";
  const slots = DOCUMENT_KINDS.map((kind) => docs[kind]);
  if (slots.some((slot) => slot.data)) return "success";
  return slots.some((slot) => slot.loading) ? "running" : "error";
}

/**
 * Ba document của một cuộc họp (Diễn biến, Giao việc, Kết luận), gọi song song: backend dùng
 * chung một lần cắt chủ đề + gán nhãn, document nào xong hiện trước. `reload(kind)` tính lại
 * riêng document đó trên cùng chủ đề; `run(request, { refreshBase: true })` tính lại tất cả.
 */
export function useMeetingDocuments() {
  // Có phiên cần khôi phục thì bắt đầu ở trạng thái đang tải (effect bên dưới lấy lại kết quả).
  const [state, setState] = useState<State>(() => {
    const session = loadSession();
    return session ? { ...INITIAL_STATE, request: session.request, docs: LOADING_DOCS } : INITIAL_STATE;
  });
  // Bản sao đồng bộ của request/document đang hiển thị, để quyết định ngay khi response về.
  const requestRef = useRef<AnalyzeV3Request | null>(null);
  const docsRef = useRef<Partial<{ [K in DocumentKind]: DocumentOf[K] }>>({});
  // Tăng mỗi lần run/reset: response của lần chạy trước (kể cả tính lại một document) bị bỏ qua.
  const runIdRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const pendingRef = useRef(0);
  const restoredRef = useRef(false);

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startTimer = useCallback(() => {
    stopTimer();
    const startedAt = Date.now();
    setState((prev) => ({ ...prev, elapsedMs: 0 }));
    timerRef.current = window.setInterval(() => {
      setState((prev) => ({ ...prev, elapsedMs: Date.now() - startedAt }));
    }, 250);
  }, [stopTimer]);

  const setSlot = useCallback(<K extends DocumentKind>(kind: K, slot: Partial<DocumentSlot<K>>) => {
    setState((prev) => ({ ...prev, docs: { ...prev.docs, [kind]: { ...prev.docs[kind], ...slot } } }));
  }, []);

  const remember = useCallback((request: AnalyzeV3Request) => {
    const documents = Object.values(docsRef.current);
    const documentKeys: Partial<Record<DocumentKind, string>> = {};
    for (const kind of DOCUMENT_KINDS) {
      const doc = docsRef.current[kind];
      if (doc) documentKeys[kind] = doc.extensions.document_key;
    }
    saveSession({ request, analysisKey: documents[0]?.extensions.input_fingerprint, documentKeys });
  }, []);

  /** Nhận một document của lần chạy `runId`; trả true nếu bản hiển thị được thay. */
  const accept = useCallback(
    <K extends DocumentKind>(kind: K, doc: DocumentOf[K], runId: number): boolean => {
      if (runId !== runIdRef.current) return false;
      const applied = isNotOlder(doc, docsRef.current[kind] ?? null);
      if (applied) {
        docsRef.current = { ...docsRef.current, [kind]: doc };
        if (requestRef.current) remember(requestRef.current);
      }
      setState((prev) => ({
        ...prev,
        docs: { ...prev.docs, [kind]: { data: applied ? doc : prev.docs[kind].data, loading: false, error: null } },
      }));
      return applied;
    },
    [remember],
  );

  const fail = useCallback(
    (kind: DocumentKind, err: unknown, runId: number) => {
      if (runId === runIdRef.current) setSlot(kind, { loading: false, error: errorMessage(err) });
    },
    [setSlot],
  );

  /** Gọi ``fetchOne`` cho mọi document song song; đồng hồ chạy tới khi document cuối về. */
  const fetchAll = useCallback(
    (runId: number, fetchOne: (kind: DocumentKind) => Promise<DocumentOf[DocumentKind]>) => {
      startTimer();
      pendingRef.current = DOCUMENT_KINDS.length;
      for (const kind of DOCUMENT_KINDS) {
        fetchOne(kind)
          .then((doc) => accept(kind, doc, runId))
          .catch((err) => fail(kind, err, runId))
          .finally(() => {
            if (runId === runIdRef.current && --pendingRef.current === 0) stopTimer();
          });
      }
    },
    [accept, fail, startTimer, stopTimer],
  );

  const run = useCallback(
    (request: AnalyzeV3Request, options: Pick<AnalyzeOptions, "refreshBase"> = {}) => {
      const runId = ++runIdRef.current;
      requestRef.current = request;
      // Tính lại tất cả thì giữ kết quả cũ trên màn hình tới khi bản mới về.
      if (!options.refreshBase) docsRef.current = {};
      saveSession({ request });
      setState((prev) => ({
        request,
        elapsedMs: 0,
        docs: options.refreshBase
          ? {
              content: { ...prev.docs.content, loading: true, error: null },
              decisions: { ...prev.docs.decisions, loading: true, error: null },
              tasks: { ...prev.docs.tasks, loading: true, error: null },
            }
          : LOADING_DOCS,
      }));
      if (!options.refreshBase) {
        fetchAll(runId, (kind) => analyzeDocument(kind, request));
        return;
      }
      // Một request tính lại nền (cắt chủ đề + nhãn); hai document kia gửi sau khi nền mới đã có,
      // để không document nào tính trên nền cũ rồi phải tính lại.
      const rebased = analyzeDocument("content", request, { refreshBase: true });
      fetchAll(runId, (kind) =>
        kind === "content" ? rebased : rebased.catch(() => undefined).then(() => analyzeDocument(kind, request)),
      );
    },
    [fetchAll],
  );

  /** Tính lại riêng `kind`. Trả true nếu bản hiển thị đã được thay bằng response mới. */
  const reload = useCallback(
    async (kind: DocumentKind): Promise<boolean> => {
      const request = requestRef.current;
      if (!request) return false;
      const runId = runIdRef.current;
      setSlot(kind, { loading: true, error: null });
      try {
        return accept(kind, await analyzeDocument(kind, request, { refresh: true }), runId);
      } catch (err) {
        fail(kind, err, runId);
        return false;
      }
    },
    [accept, fail, setSlot],
  );

  const reset = useCallback(() => {
    stopTimer();
    runIdRef.current++;
    requestRef.current = null;
    docsRef.current = {};
    saveSession(null);
    setState(INITIAL_STATE);
  }, [stopTimer]);

  // Khôi phục phiên sau khi tải lại trang (một lần; ref giữ qua lần mount kép của StrictMode).
  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    const session = loadSession();
    if (!session) return;
    const { request, analysisKey, documentKeys = {} } = session;
    const runId = ++runIdRef.current;
    requestRef.current = request;
    // `fetchAll` chỉ setState trong timer/sau await (state đang tải đã có từ lúc khởi tạo).
    // oxlint-disable-next-line react/set-state-in-effect
    fetchAll(runId, (kind) => {
      const documentKey = documentKeys[kind];
      if (!analysisKey || !documentKey) return analyzeDocument(kind, request);
      return getDocument(analysisKey, documentKey).catch((err) => {
        // Cache không còn (đổi mã nguồn/model hoặc bị xoá): về màn nhập, không tự chạy lại LLM.
        if (err instanceof ApiError && err.status === 404 && runId === runIdRef.current) reset();
        throw err;
      });
    });
  }, [fetchAll, reset]);

  return { ...state, status: analysisStatus(state.request, state.docs), run, reload, reset };
}
