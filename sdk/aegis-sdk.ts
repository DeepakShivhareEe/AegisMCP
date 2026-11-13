/**
 * AegisMCP TypeScript SDK.
 *
 * Same enforcement model as the Python SDK: guardTool authorises a tool call
 * with the gateway *before* the function runs, so a blocked call never produces
 * side effects. After the body finishes the span is completed with its output,
 * latency and usage.
 *
 * Also provides:
 *  - mcpRpc: protocol-aware MCP JSON-RPC 2.0 proxying (manifest pinning,
 *    OWASP MCP03 rug-pull detection, output screening at the gateway).
 *  - emitOtlp: export spans in OTLP/HTTP JSON with gen_ai.* attributes.
 *
 * No runtime dependencies; requires a global fetch (Node 18+, browsers, Deno).
 */

export type JsonRpcId = string | number | null;

export interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

export interface JsonRpcResponse<T = unknown> {
  jsonrpc: "2.0";
  id: JsonRpcId;
  result?: T;
  error?: JsonRpcError;
}

export type VerdictStatus = "OK" | "BLOCKED" | "PENDING_APPROVAL" | "LOOP_KILLED";

export interface ProxyVerdict {
  allowed: boolean;
  status: VerdictStatus;
  trace_id: string;
  span_id: string;
  reason?: string | null;
}

export interface SpanStatusResponse {
  span_id: string;
  trace_id: string;
  status: "OK" | "BLOCKED" | "PENDING_APPROVAL" | "ERROR";
  trace_status: string;
  guardrail_reason?: string | null;
}

export interface CompletionPayload {
  outputPayload?: unknown;
  latencyMs?: number;
  tokensUsed?: number;
  costUsd?: number;
}

export interface GuardOptions {
  spanType?: "MCP_TOOL_CALL" | "LLM_INFERENCE" | "RAG_RETRIEVAL";
  inputPayload?: Record<string, unknown>;
  tokensUsed?: number;
  costUsd?: number;
}

export interface AegisClientOptions {
  apiKey: string;
  baseUrl?: string;
  agentName?: string;
  environment?: string;
  timeoutMs?: number;
  hitlPollIntervalMs?: number;
  hitlTimeoutMs?: number;
  fetchImpl?: typeof fetch;
  onWarning?: (message: string) => void;
}

export interface OtlpSpanInput {
  name: string;
  traceId?: string;
  spanId?: string;
  parentSpanId?: string;
  model?: string;
  toolName?: string;
  prompt?: string;
  completion?: string;
  inputTokens?: number;
  outputTokens?: number;
  startTimeMs?: number;
  endTimeMs?: number;
  error?: boolean;
  attributes?: Record<string, string | number | boolean>;
}

export type OtlpAttributeValue = {
  stringValue?: string;
  intValue?: string;
  doubleValue?: number;
  boolValue?: boolean;
};

export interface OtlpKeyValue {
  key: string;
  value: OtlpAttributeValue;
}

export class AegisError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "AegisError";
    this.status = status;
  }
}

export class AegisGuardrailBlockedError extends AegisError {
  readonly reason: string;
  readonly traceId: string;
  readonly spanId: string;

  constructor(reason: string, traceId: string, spanId: string) {
    super(`Guardrail blocked: ${reason} (trace=${traceId}, span=${spanId})`);
    this.name = "AegisGuardrailBlockedError";
    this.reason = reason;
    this.traceId = traceId;
    this.spanId = spanId;
  }
}

export class AegisHitlRejectedError extends AegisError {
  readonly reason: string;
  readonly traceId: string;
  readonly spanId: string;

  constructor(reason: string, traceId: string, spanId: string) {
    super(`HITL rejected: ${reason} (trace=${traceId}, span=${spanId})`);
    this.name = "AegisHitlRejectedError";
    this.reason = reason;
    this.traceId = traceId;
    this.spanId = spanId;
  }
}

const MAX_DEPTH = 4;
const MAX_ITEMS = 50;
const MAX_STRING = 2000;

function truncate(value: string): string {
  return value.length <= MAX_STRING ? value : `${value.slice(0, MAX_STRING)}...(truncated)`;
}

/** Convert arbitrary values into JSON-safe data without throwing on cycles. */
export function toJsonable(value: unknown, depth = 0, seen = new WeakSet<object>()): unknown {
  if (value === null || typeof value === "boolean" || typeof value === "number") {
    return value;
  }
  if (typeof value === "string") {
    return truncate(value);
  }
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (typeof value === "function" || typeof value === "undefined" || typeof value === "symbol") {
    return undefined;
  }
  if (depth >= MAX_DEPTH) {
    return truncate(String(value));
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (value instanceof Error) {
    return { name: value.name, message: value.message };
  }
  if (value instanceof Map) {
    return toJsonable(Object.fromEntries(value), depth + 1, seen);
  }
  if (value instanceof Set) {
    return toJsonable(Array.from(value), depth + 1, seen);
  }
  if (Array.isArray(value)) {
    return value.slice(0, MAX_ITEMS).map((item) => toJsonable(item, depth + 1, seen));
  }
  if (typeof value === "object") {
    if (seen.has(value as object)) {
      return "[circular]";
    }
    seen.add(value as object);
    const result: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>).slice(0, MAX_ITEMS)) {
      const converted = toJsonable(item, depth + 1, seen);
      if (converted !== undefined) {
        result[key] = converted;
      }
    }
    return result;
  }
  return truncate(String(value));
}

function randomHex(bytes: number): string {
  const buffer = new Uint8Array(bytes);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(buffer);
  } else {
    for (let index = 0; index < bytes; index += 1) {
      buffer[index] = Math.floor(Math.random() * 256);
    }
  }
  return Array.from(buffer, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function attribute(value: string | number | boolean): OtlpAttributeValue {
  if (typeof value === "number") {
    return Number.isInteger(value) ? { intValue: String(value) } : { doubleValue: value };
  }
  if (typeof value === "boolean") {
    return { boolValue: value };
  }
  return { stringValue: value };
}

export class AegisClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly agentName: string;
  private readonly environment: string;
  private readonly timeoutMs: number;
  private readonly hitlPollIntervalMs: number;
  private readonly hitlTimeoutMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly onWarning?: (message: string) => void;

  private traceId: string | null = null;
  private stepIndex = 0;

  constructor(options: AegisClientOptions) {
    if (!options.apiKey) {
      throw new AegisError("apiKey is required");
    }
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/+$/, "");
    this.agentName = options.agentName ?? "typescript-agent";
    this.environment = options.environment ?? "production";
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.hitlPollIntervalMs = options.hitlPollIntervalMs ?? 1_500;
    this.hitlTimeoutMs = options.hitlTimeoutMs ?? 300_000;
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.onWarning = options.onWarning;
  }

  get currentTraceId(): string | null {
    return this.traceId;
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    extraHeaders: Record<string, string> = {},
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-Aegis-API-Key": this.apiKey,
          ...extraHeaders,
        },
      });
    } catch (error) {
      throw new AegisError(`Failed to reach ${this.baseUrl}: ${(error as Error).message}`);
    } finally {
      clearTimeout(timer);
    }

    if (!response.ok) {
      const body = await response.text().catch(() => "");
      throw new AegisError(`HTTP ${response.status}: ${body.slice(0, 500)}`, response.status);
    }
    if (response.status === 202 || response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  /** Ask the gateway for a verdict and wait out HITL before returning. */
  private async authorize(
    serverName: string,
    toolName: string,
    inputPayload: Record<string, unknown>,
    spanType: string,
    tokensUsed = 0,
    costUsd = 0,
  ): Promise<{ traceId: string; spanId: string }> {
    if (!this.traceId) {
      this.traceId = `trc_ts_${randomHex(4)}`;
    }
    const verdict = await this.request<ProxyVerdict>("/api/v1/proxy/intercept", {
      method: "POST",
      body: JSON.stringify({
        agent_name: this.agentName,
        environment: this.environment,
        span_type: spanType,
        name: toolName,
        model_or_server: serverName,
        step_index: this.stepIndex,
        tokens_used: tokensUsed,
        cost_usd: costUsd,
        input_payload: toJsonable(inputPayload) ?? {},
        trace_id: this.traceId,
      }),
    });
    this.stepIndex += 1;
    this.traceId = verdict.trace_id;

    if (verdict.status === "BLOCKED" || verdict.status === "LOOP_KILLED") {
      throw new AegisGuardrailBlockedError(
        verdict.reason ?? "Blocked by guardrails",
        verdict.trace_id,
        verdict.span_id,
      );
    }
    if (verdict.status === "PENDING_APPROVAL") {
      await this.awaitDecision(verdict.span_id, verdict.trace_id);
    }
    return { traceId: verdict.trace_id, spanId: verdict.span_id };
  }

  private async awaitDecision(spanId: string, traceId: string): Promise<void> {
    const deadline = Date.now() + this.hitlTimeoutMs;
    while (Date.now() < deadline) {
      const status = await this.request<SpanStatusResponse>(`/api/v1/spans/${spanId}/status`);
      if (status.status === "OK") {
        return;
      }
      if (status.status === "BLOCKED" || status.status === "ERROR") {
        throw new AegisHitlRejectedError(
          status.guardrail_reason ?? "Rejected by operator",
          traceId,
          spanId,
        );
      }
      await sleep(this.hitlPollIntervalMs);
    }
    throw new AegisError(`HITL timeout after ${this.hitlTimeoutMs}ms for span ${spanId}`);
  }

  private async complete(spanId: string, payload: CompletionPayload): Promise<void> {
    if (!spanId) {
      return;
    }
    try {
      await this.request(`/api/v1/spans/${spanId}/complete`, {
        method: "POST",
        body: JSON.stringify({
          output_payload: toJsonable(payload.outputPayload) ?? null,
          latency_ms: payload.latencyMs ?? 0,
          tokens_used: payload.tokensUsed ?? 0,
          cost_usd: payload.costUsd ?? 0,
        }),
      });
    } catch (error) {
      this.onWarning?.(`AegisMCP span completion failed: ${(error as Error).message}`);
    }
  }

  /**
   * Guard one tool call: authorise first, run the body, then complete the span.
   * A blocked call throws before `fn` is invoked.
   */
  async guardTool<T>(
    serverName: string,
    toolName: string,
    fn: () => T | Promise<T>,
    options: GuardOptions = {},
  ): Promise<T> {
    const inputPayload = options.inputPayload ?? {};
    const authorized = await this.authorize(
      serverName,
      toolName,
      inputPayload,
      options.spanType ?? "MCP_TOOL_CALL",
      options.tokensUsed,
      options.costUsd,
    );

    const startedAt = Date.now();
    let result: T;
    try {
      result = await fn();
    } catch (error) {
      await this.complete(authorized.spanId, {
        outputPayload: { error: (error as Error).message },
        latencyMs: Date.now() - startedAt,
        tokensUsed: options.tokensUsed,
        costUsd: options.costUsd,
      });
      throw error;
    }

    await this.complete(authorized.spanId, {
      outputPayload: result,
      latencyMs: Date.now() - startedAt,
      tokensUsed: options.tokensUsed,
      costUsd: options.costUsd,
    });
    return result;
  }

  /**
   * Send one MCP JSON-RPC 2.0 message through the gateway.
   * Inspect `response.error` for policy rejections (BLOCKED, PENDING_APPROVAL,
   * rug pull, output injection).
   */
  async mcpRpc<T = unknown>(
    serverName: string,
    method: string,
    params: Record<string, unknown> = {},
    id: JsonRpcId = `${Date.now()}`,
  ): Promise<JsonRpcResponse<T>> {
    return this.request<JsonRpcResponse<T>>(
      `/api/v1/mcp/${encodeURIComponent(serverName)}/rpc`,
      {
        method: "POST",
        body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
      },
    );
  }

  /** Discover tools; throws when the gateway rejects the manifest. */
  async listTools(serverName: string): Promise<Array<Record<string, unknown>>> {
    const response = await this.mcpRpc<{ tools: Array<Record<string, unknown>> }>(
      serverName,
      "tools/list",
    );
    if (response.error) {
      throw new AegisError(
        `tools/list rejected (${response.error.code}): ${response.error.message}`,
      );
    }
    return response.result?.tools ?? [];
  }

  /** Emit spans to POST /api/v1/otlp/v1/traces using a bearer API key. */
  async emitOtlp(
    spans: OtlpSpanInput[],
    resourceAttributes: Record<string, string | number | boolean> = {},
  ): Promise<{ partialSuccess?: { rejectedSpans?: number; errorMessage?: string } }> {
    const spanAttributes = (span: OtlpSpanInput): OtlpKeyValue[] => {
      const attributes: OtlpKeyValue[] = [];
      if (span.model) {
        attributes.push({ key: "gen_ai.request.model", value: attribute(span.model) });
        attributes.push({ key: "gen_ai.system", value: attribute(span.model.split("-")[0] ?? "unknown") });
      }
      if (span.toolName) {
        attributes.push({ key: "mcp.tool.name", value: attribute(span.toolName) });
        attributes.push({ key: "gen_ai.operation.name", value: attribute("execute_tool") });
      }
      if (typeof span.inputTokens === "number") {
        attributes.push({
          key: "gen_ai.usage.input_tokens",
          value: attribute(span.inputTokens),
        });
      }
      if (typeof span.outputTokens === "number") {
        attributes.push({
          key: "gen_ai.usage.output_tokens",
          value: attribute(span.outputTokens),
        });
      }
      if (span.prompt) {
        attributes.push({ key: "gen_ai.prompt", value: attribute(span.prompt) });
      }
      if (span.completion) {
        attributes.push({ key: "gen_ai.completion", value: attribute(span.completion) });
      }
      for (const [key, value] of Object.entries(span.attributes ?? {})) {
        attributes.push({ key, value: attribute(value) });
      }
      return attributes;
    };

    const payload = {
      resourceSpans: [
        {
          resource: {
            attributes: [
              { key: "service.name", value: attribute(this.agentName) },
              { key: "deployment.environment", value: attribute(this.environment) },
              ...Object.entries(resourceAttributes).map(([key, value]) => ({
                key,
                value: attribute(value),
              })),
            ],
          },
          scopeSpans: [
            {
              scope: { name: "aegis-sdk-ts", version: "1.0.0" },
              spans: spans.map((span) => {
                const endTime = span.endTimeMs ?? Date.now();
                const startTime = span.startTimeMs ?? endTime;
                return {
                  traceId: span.traceId ?? randomHex(16),
                  spanId: span.spanId ?? randomHex(8),
                  parentSpanId: span.parentSpanId,
                  name: span.name,
                  kind: span.toolName ? 3 : 1,
                  startTimeUnixNano: `${startTime}000000`,
                  endTimeUnixNano: `${endTime}000000`,
                  attributes: spanAttributes(span),
                  status: { code: span.error ? 2 : 1 },
                };
              }),
            },
          ],
        },
      ],
    };

    return this.request(
      "/api/v1/otlp/v1/traces",
      { method: "POST", body: JSON.stringify(payload) },
      { Authorization: `Bearer ${this.apiKey}` },
    );
  }
}

export function createClient(options: AegisClientOptions): AegisClient {
  return new AegisClient(options);
}
