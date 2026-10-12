import type { AnalyzeV3Request, DocumentKind, DocumentOf } from "./types";

// Empty by default: dev uses the Vite proxy (vite.config.ts) for same-origin
// requests; production deploys should set VITE_API_BASE_URL to wherever
// `uvicorn --app-dir be main:app` is reachable.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body.detail ?? body);
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/health`);
    if (!response.ok) return false;
    const body = (await response.json()) as { status?: string };
    return body.status === "ok";
  } catch {
    return false;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(
      `Không kết nối được tới API (${API_BASE_URL || "cùng origin"}). Backend đã chạy chưa?`,
    );
  }
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return (await response.json()) as T;
}

export interface AnalyzeOptions {
  /** Tính lại document này trên cùng chủ đề + nhãn. */
  refresh?: boolean;
  /** Tính lại cả cắt chủ đề + nhãn (gọi LLM thật cho mọi bước). */
  refreshBase?: boolean;
}

/**
 * Một document của cuộc họp (`POST /v3/meetings/{kind}`). Backend dùng lại cache nếu có; ba
 * document của cùng transcript dùng chung một lần cắt chủ đề + gán nhãn, nên gọi song song được.
 */
export function analyzeDocument<K extends DocumentKind>(
  kind: K,
  payload: AnalyzeV3Request,
  options: AnalyzeOptions = {},
): Promise<DocumentOf[K]> {
  const query = new URLSearchParams();
  if (options.refresh) query.set("refresh", "true");
  if (options.refreshBase) query.set("refresh_base", "true");
  const suffix = query.toString() ? `?${query}` : "";
  return requestJson<DocumentOf[K]>(`/v3/meetings/${kind}${suffix}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** Document đã cache, không gọi LLM; `ApiError` 404 nếu cache không còn. */
export function getDocument<K extends DocumentKind>(analysisKey: string, documentKey: string): Promise<DocumentOf[K]> {
  return requestJson<DocumentOf[K]>(
    `/v3/meetings/analyses/${encodeURIComponent(analysisKey)}/${encodeURIComponent(documentKey)}`,
  );
}
