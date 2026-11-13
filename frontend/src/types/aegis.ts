export type TraceStatus = "RUNNING" | "COMPLETED" | "BLOCKED" | "PENDING_HITL" | "LOOP_KILLED";
export type SpanStatus = "OK" | "BLOCKED" | "PENDING_APPROVAL" | "ERROR";
export type SpanType = "LLM_INFERENCE" | "MCP_TOOL_CALL" | "RAG_RETRIEVAL" | "GUARDRAIL_INTERCEPT";
export type TransportType = "stdio" | "sse" | "websocket";
export type ServerStatus = "ONLINE" | "DEGRADED" | "OFFLINE";
export type PermissionMode = "ALLOW_ALL" | "READ_ONLY" | "HITL_REQUIRED" | "STRICT_BLOCK";

export interface MCPServer {
  id: string;
  name: string;
  endpoint_url: string;
  transport: TransportType;
  status: ServerStatus;
  permission_mode: PermissionMode;
  max_cost_usd_per_run: number;
  max_steps_per_run: number;
  blocked_patterns: string[];
  created_at: string;
}

export interface AgentTrace {
  id: string;
  agent_name: string;
  environment: string;
  org_id: string;
  status: TraceStatus;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_cost_usd: number;
  total_latency_ms: number;
  step_count: number;
  started_at: string;
  ended_at: string | null;
  mcp_server_id: string | null;
}

export interface TraceSpan {
  id: string;
  requester_id?: string | null;
  trace_id: string;
  parent_span_id: string | null;
  step_index: number;
  span_type: SpanType;
  name: string;
  model_or_server: string;
  status: SpanStatus;
  latency_ms: number;
  tokens_used: number;
  cost_usd: number;
  input_payload: Record<string, any> | null;
  output_payload: Record<string, any> | null;
  guardrail_reason: string | null;
  created_at: string;
}

export interface SpanIngestRequest {
  trace_id: string;
  agent_name: string;
  environment: string;
  span_type: SpanType;
  name: string;
  model_or_server: string;
  parent_span_id?: string | null;
  step_index: number;
  latency_ms?: number;
  tokens_used?: number;
  cost_usd?: number;
  input_payload?: Record<string, any> | null;
  output_payload?: Record<string, any> | null;
}

export interface SpanIngestResponse {
  span_id: string;
  trace_id: string;
  span_status: SpanStatus;
  trace_status: TraceStatus;
  guardrail_reason: string | null;
  blocked: boolean;
}

export interface SpanDecisionRequest {
  action: "APPROVE" | "REJECT";
  reviewer_note: string;
}

export interface SpanDecisionResponse {
  span_id: string;
  action: "APPROVE" | "REJECT";
  trace_id: string;
  trace_status: TraceStatus;
}

export interface SessionResponse {
  operator_id: string;
  org_id: string;
  role: "admin" | "auditor";
  expires_in: number;
}

export interface MeResponse {
  authenticated: boolean;
  operator_id: string | null;
  org_id: string | null;
  role: string | null;
  csrf_active: boolean;
  rate_limit_remaining: number | null;
}

export interface AnalyticsSummary {
  total_spend_24h_usd: number;
  active_sessions: number;
  guardrail_interceptions: number;
  mean_ttft_ms: number;
  model_cost_breakdown: Record<string, number>;
  hourly_token_series: Array<{ hour: string; tokens: number }>;
}

export interface HealthResponse {
  status: string;
  database: string;
  version: string;
}

export interface SecurityStatus {
  csrfActive: boolean;
  rateLimitRemaining: number | null;
  sessionAuthenticated: boolean;
}

export interface SimulatorTriggerRequest {
  agent_name?: string;
  environment?: string;
}

export interface SimulatorTriggerResponse {
  trace_id: string;
  agent_name: string;
  status: TraceStatus;
  spans_created: number;
}

export interface APIKey {
  id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface APIKeyCreateResponse {
  id: string;
  name: string;
  key_prefix: string;
  raw_key: string;
  created_at: string;
}

export interface HitlPendingItem {
  span_id: string;
  trace_id: string;
  agent_name: string;
  name: string;
  model_or_server: string;
  input_payload: Record<string, any> | null;
  guardrail_reason: string | null;
  created_at: string;
}

export interface HitlPendingResponse {
  items: HitlPendingItem[];
}

export interface ProxyInterceptRequest {
  agent_name: string;
  environment?: string;
  span_type: SpanType;
  name: string;
  model_or_server: string;
  parent_span_id?: string | null;
  step_index?: number;
  latency_ms?: number;
  tokens_used?: number;
  cost_usd?: number;
  input_payload?: Record<string, any> | null;
  output_payload?: Record<string, any> | null;
  trace_id?: string | null;
}

export interface ProxyInterceptResponse {
  allowed: boolean;
  status: "OK" | "BLOCKED" | "PENDING_APPROVAL" | "LOOP_KILLED";
  trace_id: string;
  span_id: string;
  reason: string | null;
}

export interface SpanStatusResponse {
  span_id: string;
  trace_id: string;
  status: SpanStatus;
  trace_status: TraceStatus;
  guardrail_reason: string | null;
}