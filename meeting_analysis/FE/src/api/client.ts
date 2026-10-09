import type {
  AnalyzeRequest,
  AnalyzeResponse,
  AnalyzeV3Request,
  AnalyzeV3Result,
} from "./types";

// Empty by default: dev uses the Vite proxy (vite.config.ts) for same-origin
// requests; production deploys should set VITE_API_BASE_URL to wherever
// `uvicorn api:app` (be/) is reachable.
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

export async function analyzeMeeting(payload: AnalyzeRequest): Promise<AnalyzeResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/meetings/analyze`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ApiError(
      `Không kết nối được tới API (${API_BASE_URL || "cùng origin"}). Backend đã chạy chưa?`,
    );
  }

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as AnalyzeResponse;
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

/** Pipeline v3: chạy một mạch tới kết quả (Verifier và agent trích xuất tự đồng thuận, không duyệt người). */
export function analyzeMeetingV3(payload: AnalyzeV3Request): Promise<AnalyzeV3Result> {
  return requestJson<AnalyzeV3Result>("/v3/meetings/analyze", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}
