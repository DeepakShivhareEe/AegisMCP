import type {
  SpanIngestRequest,
  SpanIngestResponse,
  SpanDecisionRequest,
  SpanDecisionResponse,
  SimulatorTriggerRequest,
  SimulatorTriggerResponse,
  AgentTrace,
  TraceSpan,
  MCPServer,
  MeResponse,
  AnalyticsSummary,
  HealthResponse,
  SessionResponse,
  APIKey,
  APIKeyCreateResponse,
  HitlPendingResponse,
  HitlPendingItem,
  ProxyInterceptRequest,
  ProxyInterceptResponse,
  SpanStatusResponse,
} from "@/types/aegis";

import { ApiError } from "./errors";

export type { MeResponse };

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

let csrfToken: string | null = null;

export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|; )aegis_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

export async function bootstrapSession(): Promise<void> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/session`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        operator_id: "operator-1",
        org_id: "org-1",
        role: "admin",
      }),
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => "");
      throw new ApiError(res.status, res.statusText, errText);
    }

    csrfToken = getCsrfToken();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(0, "Network Error", "Unable to connect to Aegis backend session service");
  }
}

export async function ensureCsrfToken(): Promise<string | null> {
  if (!csrfToken) {
    csrfToken = getCsrfToken();
    if (!csrfToken) {
      try {
        await bootstrapSession();
        csrfToken = getCsrfToken();
      } catch {
        // Return null if bootstrap cannot be reached; request will still attempt
        return null;
      }
    }
  }
  return csrfToken;
}

export async function request<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  retryOnUnauthorized = true
): Promise<T> {
  const isMutating = method === "POST" || method === "PATCH" || method === "DELETE";

  const headers: Record<string, string> = {
    Accept: "application/json",
  };

  if (isMutating) {
    headers["Content-Type"] = "application/json";
    const token = await ensureCsrfToken();
    if (token) {
      headers["X-CSRF-Token"] = token;
    }
  } else if (body) {
    headers["Content-Type"] = "application/json";
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      credentials: "include",
      headers,
      body: isMutating ? JSON.stringify(body ?? {}) : (body ? JSON.stringify(body) : undefined),
    });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Network error";
    throw new ApiError(
      0,
      "Connection Failed",
      `Failed to connect to Aegis API at ${API_BASE_URL}${path}. Please verify the backend service is running. (${msg})`
    );
  }

  if (!res.ok) {
    let parsedData: unknown;
    try {
      parsedData = await res.json();
    } catch {
      parsedData = await res.text().catch(() => "");
    }

    // If CSRF mismatch occurred on mutating request, reset token and throw
    if (res.status === 403 && isMutating) {
      csrfToken = null;
    }

    // Expired/absent session: mint a fresh one and retry exactly once.
    if (retryOnUnauthorized && res.status === 401 && path !== "/api/v1/auth/session") {
      try {
        await bootstrapSession();
        return await request<T>(method, path, body, false);
      } catch {
        // Fall through and surface the original 401.
      }
    }

    throw new ApiError(res.status, res.statusText, parsedData);
  }

  // Update CSRF token from cookie if available
  const currentCookie = getCsrfToken();
  if (currentCookie) {
    csrfToken = currentCookie;
  }

  if (res.status === 204) return undefined as unknown as T;
  return res.json();
}

export async function requestWithApiKey<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  apiKey: string,
  body?: unknown
): Promise<T> {
  const isMutating = method === "POST" || method === "PATCH" || method === "DELETE";

  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Aegis-API-Key": apiKey,
  };

  if (isMutating || body) {
    headers["Content-Type"] = "application/json";
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: isMutating || body ? JSON.stringify(body ?? {}) : undefined,
    });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Network error";
    throw new ApiError(
      0,
      "Connection Failed",
      `Failed to connect to Aegis API at ${API_BASE_URL}${path}. Please verify the backend service is running. (${msg})`
    );
  }

  if (!res.ok) {
    let parsedData: unknown;
    try {
      parsedData = await res.json();
    } catch {
      parsedData = await res.text().catch(() => "");
    }
    throw new ApiError(res.status, res.statusText, parsedData);
  }

  if (res.status === 204) return undefined as unknown as T;
  return res.json();
}

export function createEventSource(url: string): EventSource {
  return new EventSource(url, { withCredentials: true });
}

export const api = {
  health: (): Promise<HealthResponse> => request("GET", "/api/v1/health"),
  me: (): Promise<MeResponse> => request("GET", "/api/v1/auth/me"),
  session: (body: { operator_id?: string; org_id?: string; role?: string }): Promise<SessionResponse> =>
    request("POST", "/api/v1/auth/session", body),
  traces: (): Promise<AgentTrace[]> => request("GET", "/api/v1/traces"),
  traceDetail: (traceId: string): Promise<{ trace: AgentTrace; spans: TraceSpan[] }> =>
    request("GET", `/api/v1/traces/${traceId}`),
  ingestSpan: (body: SpanIngestRequest): Promise<SpanIngestResponse> =>
    request("POST", "/api/v1/ingest/span", body),
  simulatorTrigger: (body?: SimulatorTriggerRequest): Promise<SimulatorTriggerResponse> =>
    request("POST", "/api/v1/simulator/trigger", body),
  mcpServers: (): Promise<MCPServer[]> => request("GET", "/api/v1/mcp-servers"),
  patchMcpServer: (serverId: string, body: Record<string, unknown>): Promise<MCPServer> =>
    request("PATCH", `/api/v1/mcp-servers/${serverId}`, body),
  spanDecision: (spanId: string, body: SpanDecisionRequest): Promise<SpanDecisionResponse> =>
    request("POST", `/api/v1/spans/${spanId}/decision`, body),
  analytics: (): Promise<AnalyticsSummary> => request("GET", "/api/v1/analytics/summary"),
  // New endpoints
  hitlPending: (): Promise<HitlPendingResponse> => request("GET", "/api/v1/hitl/pending"),
  apiKeys: (): Promise<APIKey[]> => request("GET", "/api/v1/api-keys"),
  createApiKey: (body: { name: string }): Promise<APIKeyCreateResponse> =>
    request("POST", "/api/v1/api-keys", body),
  deleteApiKey: (keyId: string): Promise<{ status: string; key_id: string }> =>
    request("DELETE", `/api/v1/api-keys/${keyId}`),
  proxyIntercept: (body: ProxyInterceptRequest, apiKey: string): Promise<ProxyInterceptResponse> =>
    requestWithApiKey("POST", "/api/v1/proxy/intercept", apiKey, body),
  spanStatus: (spanId: string, apiKey: string): Promise<SpanStatusResponse> =>
    requestWithApiKey("GET", `/api/v1/spans/${spanId}/status`, apiKey),
};
