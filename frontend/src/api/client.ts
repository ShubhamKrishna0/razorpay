/** Thin typed fetch wrapper. One place knows the base URL and the error shape. */

import type {
  Breakdown, BenchmarkResponse, ChatResponse, DatasetInfo, EngineConfig,
  ExceptionPage, ExceptionRow, RunDetail, RunSummary,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const API = `${BASE}/api`;

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body; the status text is all we have */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const qs = (params: Record<string, string | number | undefined>): string => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  return entries.length ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}` : "";
};

export const api = {
  config: () => request<EngineConfig>("/config"),

  listDatasets: () => request<DatasetInfo[]>("/datasets"),
  generateDataset: (size: number, seed = 42, label?: string) =>
    request<DatasetInfo>("/datasets", {
      method: "POST",
      body: JSON.stringify({ size, seed, label }),
    }),
  uploadDataset: (form: FormData) =>
    fetch(`${API}/datasets/upload`, { method: "POST", body: form }).then(async (r) => {
      if (!r.ok) throw new ApiError(r.status, await r.text());
      return (await r.json()) as DatasetInfo;
    }),

  listRuns: (limit = 25) => request<RunSummary[]>(`/runs${qs({ limit })}`),
  startRun: (datasetId: string, useAi: boolean, label?: string) =>
    request<RunSummary>("/runs", {
      method: "POST",
      body: JSON.stringify({ dataset_id: datasetId, use_ai: useAi, label }),
    }),
  getRun: (runId: string) => request<RunDetail>(`/runs/${runId}`),
  getBreakdown: (runId: string) => request<Breakdown>(`/runs/${runId}/breakdown`),
  getCascade: (runId: string) => request<RunDetail["manifest"]>(`/runs/${runId}/cascade`),

  listExceptions: (
    runId: string,
    opts: { exception_type?: string; resolution?: string; merchant_id?: string;
            offset?: number; limit?: number } = {},
  ) => request<ExceptionPage>(`/runs/${runId}/exceptions${qs(opts)}`),
  getException: (runId: string, caseId: string) =>
    request<ExceptionRow>(`/runs/${runId}/exceptions/${encodeURIComponent(caseId)}`),
  investigate: (runId: string, caseId: string) =>
    request<{ case_id: string; verdict: Record<string, unknown> }>(
      `/runs/${runId}/exceptions/${encodeURIComponent(caseId)}/investigate`,
      { method: "POST" },
    ),
  review: (runId: string, caseId: string, decision: string, note?: string) =>
    request<{ recorded: boolean }>(
      `/runs/${runId}/exceptions/${encodeURIComponent(caseId)}/review`,
      { method: "POST", body: JSON.stringify({ decision, note, reviewer: "operator" }) },
    ),

  chat: (runId: string, question: string) =>
    request<ChatResponse>("/finance/chat", {
      method: "POST",
      body: JSON.stringify({ run_id: runId, question }),
    }),

  getBenchmark: () => request<BenchmarkResponse>("/benchmark"),
  runBenchmark: (sizes?: number[], seed = 42) =>
    request<BenchmarkResponse>("/benchmark", {
      method: "POST",
      body: JSON.stringify({ sizes, seed }),
    }),
};
