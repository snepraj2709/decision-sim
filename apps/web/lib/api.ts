/**
 * API client — typed wrapper around the FastAPI backend.
 * Types derived from GET http://localhost:8000/openapi.json.
 */

import type { Confidence } from "@/lib/confidence";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public payload?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let payload: unknown;
    try {
      payload = await res.json();
    } catch {
      /* ignore */
    }
    throw new ApiError(`API ${res.status} on ${path}`, res.status, payload);
  }
  return res.json() as Promise<T>;
}

// ─── Polling ─────────────────────────────────────────────────────────────────

const BACKOFF_MS = [500, 1000, 2000, 4000, 8000];
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollUntilDone<T extends { status: string }>(
  fn: () => Promise<T>,
  onTick?: (result: T) => void,
): Promise<T> {
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  let attempt = 0;
  while (true) {
    const result = await fn();
    onTick?.(result);
    if (result.status === "finished" || result.status === "failed") {
      return result;
    }
    if (Date.now() >= deadline) throw new Error("Polling timed out after 5 minutes");
    await sleep(BACKOFF_MS[Math.min(attempt++, BACKOFF_MS.length - 1)]);
  }
}

// ─── Types ───────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: "ok";
  env: string;
  version: string;
}

export interface ConfidentField {
  value: string;
  confidence: Confidence;
  sources: number;
}

export interface ProductSnapshot {
  id: string;
  product_id: string;
  created_at: string;
  category: ConfidentField | null;
  value_prop: ConfidentField | null;
  pricing: ConfidentField | null;
  features: ConfidentField | null;
  audience: ConfidentField | null;
  competitors: ConfidentField | null;
}

export interface DriverWeight {
  label: string;
  weight: number;
}

export interface Evidence {
  id: string;
  quote: string;
  source: string;
  source_url: string | null;
  kind: "reddit" | "g2" | "twitter" | "capterra" | "review" | "press" | "other";
  captured_at: string | null;
}

export interface Segment {
  id: string;
  name: string;
  descriptor: string | null;
  job_to_be_done: string | null;
  share_pct: number | null;
  confidence: Confidence;
  drivers: DriverWeight[] | null;
  leaves: string | null;
  evidence: Evidence[];
}

export interface DecisionOption {
  label: string;
  description: string;
  option_type: "pricing" | "copy" | "feature" | "bundling" | "onboarding";
}

export interface OptionInput {
  letter: string;
  title: string;
  sub: string | null;
}

export type ReactionSentiment = "positive" | "neutral" | "negative" | "mixed";

export interface SimulationCell {
  id: string;
  segment_id: string;
  option_letter: string;
  range_low: number;
  range_high: number;
  confidence: Confidence;
  reasoning_trace: string | null;
  top_concern: string | null;
  invalidating_experiment: string | null;
  reaction_sentiment: string | null;
  adoption_probability: number | null;
  time_horizon: string | null;
  devil_advocate: string | null;
}

export interface Simulation {
  id: string;
  snapshot_id: string;
  decision_type: "pricing" | "copy" | "feature" | "bundle" | "onboarding";
  options: OptionInput[];
  status: "pending" | "running" | "completed" | "failed";
  overall_confidence: Confidence | null;
  created_at: string;
  completed_at: string | null;
  cells: SimulationCell[];
}

export interface SnapshotJobResponse {
  job_id: string;
  status_url: string;
}

export interface SnapshotJobStatus {
  status: "queued" | "started" | "finished" | "failed";
  snapshot_id: string | null;
  error: string | null;
}

export interface ICPJobResponse {
  job_id: string;
  status_url: string;
}

export interface ICPJobStatus {
  status: "queued" | "started" | "finished" | "failed";
  segment_ids: string[] | null;
  error: string | null;
}

export interface SimulationJobResponse {
  simulation_id: string;
  job_id: string;
  status_url: string;
}

export interface SimulationJobStatus {
  status: "queued" | "started" | "finished" | "failed";
  simulation_id: string | null;
  error: string | null;
}

// ─── API ─────────────────────────────────────────────────────────────────────

export const api = {
  health: () => request<HealthResponse>("/api/v1/health"),

  createSnapshot: (url: string) =>
    request<SnapshotJobResponse>("/api/v1/snapshots", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),

  pollSnapshotJob: (
    jobId: string,
    onTick?: (s: SnapshotJobStatus) => void,
  ) =>
    pollUntilDone(
      () => request<SnapshotJobStatus>(`/api/v1/snapshots/jobs/${jobId}`),
      onTick,
    ),

  getSnapshot: (snapshotId: string) =>
    request<ProductSnapshot>(`/api/v1/snapshots/${snapshotId}`),

  createICPs: (snapshotId: string) =>
    request<ICPJobResponse>(`/api/v1/snapshots/${snapshotId}/icps`, {
      method: "POST",
    }),

  pollICPJob: (jobId: string, onTick?: (s: ICPJobStatus) => void) =>
    pollUntilDone(
      () => request<ICPJobStatus>(`/api/v1/icps/jobs/${jobId}`),
      onTick,
    ),

  getSegments: (snapshotId: string) =>
    request<Segment[]>(`/api/v1/snapshots/${snapshotId}/segments`),

  createSimulation: (snapshotId: string, options: DecisionOption[]) =>
    request<SimulationJobResponse>(
      `/api/v1/snapshots/${snapshotId}/simulate`,
      {
        method: "POST",
        body: JSON.stringify({ options }),
      },
    ),

  pollSimulationJob: (
    jobId: string,
    onTick?: (s: SimulationJobStatus) => void,
  ) =>
    pollUntilDone(
      () =>
        request<SimulationJobStatus>(`/api/v1/simulations/jobs/${jobId}`),
      onTick,
    ),

  getSimulation: (simulationId: string) =>
    request<Simulation>(`/api/v1/simulations/${simulationId}`),
};

export { ApiError };
