/**
 * API client — typed wrapper around the FastAPI backend.
 *
 * Step 1 only ships a health check. Steps 2–4 add real endpoints; this client
 * grows alongside them. By the end of Step 4 we'll codegen this from OpenAPI;
 * until then, types are written by hand and mirror the Pydantic schemas.
 */

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
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let payload: unknown;
    try { payload = await res.json(); } catch { /* ignore */ }
    throw new ApiError(
      `API ${res.status} on ${path}`,
      res.status,
      payload,
    );
  }
  return res.json() as Promise<T>;
}

// ─── Endpoints ─────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: "ok";
  env: string;
  version: string;
}

export const api = {
  health: () => request<HealthResponse>("/api/v1/health"),
  // snapshots, icps, simulations come in Steps 2–4
};

export { ApiError };
