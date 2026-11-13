"""Pydantic v2 schemas for AegisMCP API request/response models."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import (
    PermissionMode,
    ServerStatus,
    SpanStatus,
    SpanType,
    TraceStatus,
    TransportType,
)

__all__ = [
    "AgentTraceBase",
    "AgentTraceCreate",
    "AgentTraceResponse",
    "AnalyticsSummary",
    "APIKeyBase",
    "APIKeyCreate",
    "APIKeyCreateResponse",
    "APIKeyResponse",
    "ErrorResponse",
    "HealthResponse",
    "HitlPendingItem",
    "HitlPendingResponse",
    "MCPServerBase",
    "MCPServerCreate",
    "MCPServerResponse",
    "MCPServerUpdate",
    "MeResponse",
    "PermissionMode",
    "ProxyInterceptRequest",
    "ProxyInterceptResponse",
    "ServerStatus",
    "SessionCreateRequest",
    "SessionResponse",
    "SimulatorTriggerRequest",
    "SimulatorTriggerResponse",
    "SpanDecisionRequest",
    "SpanCompleteRequest",
    "SpanCompleteResponse",
    "SpanDecisionResponse",
    "SpanIngestRequest",
    "SpanIngestResponse",
    "SpanStatus",
    "SpanType",
    "SpanStatusResponse",
    "TraceSpanBase",
    "TraceSpanCreate",
    "TraceDetailResponse",
    "TraceSpanResponse",
    "TraceStatus",
    "TransportType",
]

# Guardrail pattern limits, shared with app.services.guardrail_engine.
MAX_BLOCKED_PATTERN_LENGTH = 200
MAX_BLOCKED_PATTERN_COUNT = 50


def _validate_blocked_patterns(patterns: list[str]) -> list[str]:
    """Cap pattern count/length so user-supplied regexes cannot be abusive."""
    if len(patterns) > MAX_BLOCKED_PATTERN_COUNT:
        raise ValueError(f"at most {MAX_BLOCKED_PATTERN_COUNT} blocked patterns are allowed")
    cleaned: list[str] = []
    for pattern in patterns:
        stripped = pattern.strip()
        if not stripped:
            continue
        if len(stripped) > MAX_BLOCKED_PATTERN_LENGTH:
            raise ValueError(
                f"each blocked pattern must be at most {MAX_BLOCKED_PATTERN_LENGTH} characters"
            )
        cleaned.append(stripped)
    return cleaned


class MCPServerBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    endpoint_url: str = Field(..., min_length=1, max_length=500)
    transport: TransportType
    status: ServerStatus = ServerStatus.ONLINE
    permission_mode: PermissionMode = PermissionMode.ALLOW_ALL
    max_cost_usd_per_run: float = Field(default=0.50, ge=0)
    max_steps_per_run: int = Field(default=15, ge=1)
    blocked_patterns: list[str] = Field(default_factory=list)

    @field_validator("blocked_patterns")
    @classmethod
    def _check_blocked_patterns(cls, value: list[str]) -> list[str]:
        return _validate_blocked_patterns(value)


class MCPServerCreate(MCPServerBase):
    pass


class MCPServerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    endpoint_url: str | None = Field(default=None, min_length=1, max_length=500)
    transport: TransportType | None = None
    status: ServerStatus | None = None
    permission_mode: PermissionMode | None = None
    max_cost_usd_per_run: float | None = Field(default=None, ge=0)
    max_steps_per_run: int | None = Field(default=None, ge=1)
    blocked_patterns: list[str] | None = None

    @field_validator("blocked_patterns")
    @classmethod
    def _check_blocked_patterns(cls, value: list[str] | None) -> list[str] | None:
        return _validate_blocked_patterns(value) if value is not None else None


class MCPServerResponse(MCPServerBase):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, from_attributes=True)

    id: str
    created_at: datetime
    tool_manifest_hash: str | None = None


class AgentTraceBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agent_name: str = Field(..., min_length=1, max_length=255)
    environment: str = Field(..., min_length=1, max_length=100)
    status: TraceStatus = TraceStatus.RUNNING
    total_tokens: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0)
    total_latency_ms: int = Field(default=0, ge=0)
    step_count: int = Field(default=0, ge=0)


class AgentTraceCreate(AgentTraceBase):
    pass


class AgentTraceResponse(AgentTraceBase):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, from_attributes=True)

    id: str
    org_id: str
    mcp_server_id: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


class TraceSpanBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trace_id: str
    parent_span_id: str | None = None
    step_index: int = Field(..., ge=0)
    span_type: SpanType
    name: str = Field(..., min_length=1, max_length=255)
    model_or_server: str = Field(..., min_length=1, max_length=255)
    status: SpanStatus = SpanStatus.OK
    latency_ms: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    input_payload: dict[str, Any] | None = None
    output_payload: dict[str, Any] | None = None
    guardrail_reason: str | None = None


class TraceSpanCreate(TraceSpanBase):
    pass


class TraceSpanResponse(TraceSpanBase):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, from_attributes=True)

    id: str
    created_at: datetime
    requester_id: str | None = None


class TraceDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trace: AgentTraceResponse
    spans: list[TraceSpanResponse]


class SpanIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trace_id: str = Field(..., min_length=1)
    agent_name: str = Field(..., min_length=1, max_length=255)
    environment: str = Field(default="production", min_length=1, max_length=100)
    span_type: SpanType
    name: str = Field(..., min_length=1, max_length=255)
    model_or_server: str = Field(..., min_length=1, max_length=255)
    parent_span_id: str | None = None
    step_index: int = Field(..., ge=0)
    latency_ms: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    input_payload: dict[str, Any] | None = None
    output_payload: dict[str, Any] | None = None


class SpanIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    span_id: str
    trace_id: str
    span_status: SpanStatus
    trace_status: TraceStatus
    guardrail_reason: str | None = None
    blocked: bool = False


class SimulatorTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agent_name: str = Field(default="simulated-agent", min_length=1, max_length=255)
    environment: str = Field(default="production", min_length=1, max_length=100)


class SimulatorTriggerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trace_id: str
    agent_name: str
    status: TraceStatus
    spans_created: int


class SpanDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["APPROVE", "REJECT"]
    reviewer_note: str = Field(..., min_length=1, max_length=1000)


class SpanDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    span_id: str
    action: Literal["APPROVE", "REJECT"]
    trace_id: str
    trace_status: TraceStatus


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operator_id: str = Field(default="operator-1", min_length=1)
    org_id: str = Field(default="org-1", min_length=1)
    role: Literal["admin", "auditor"] = Field(default="admin")


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operator_id: str
    org_id: str
    role: Literal["admin", "auditor"]
    expires_in: int


class MeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    authenticated: bool
    operator_id: str | None = None
    org_id: str | None = None
    role: str | None = None
    csrf_active: bool = False
    rate_limit_remaining: int | None = None


class AnalyticsSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    total_spend_24h_usd: float
    active_sessions: int
    guardrail_interceptions: int
    mean_ttft_ms: float
    model_cost_breakdown: dict[str, float]
    hourly_token_series: list[dict[str, Any]]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: str
    database: str
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    error: str
    detail: str | None = None
    status_code: int


class APIKeyBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)


class APIKeyCreate(APIKeyBase):
    pass


class APIKeyCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    name: str
    key_prefix: str
    raw_key: str
    created_at: datetime


class APIKeyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, from_attributes=True)

    id: str
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None


class HitlPendingItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    span_id: str
    trace_id: str
    agent_name: str
    name: str
    model_or_server: str
    input_payload: dict[str, Any] | None = None
    guardrail_reason: str | None = None
    created_at: datetime


class HitlPendingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    items: list[HitlPendingItem]


class ProxyInterceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agent_name: str = Field(..., min_length=1, max_length=255)
    environment: str = Field(default="production", min_length=1, max_length=100)
    span_type: SpanType
    name: str = Field(..., min_length=1, max_length=255)
    model_or_server: str = Field(..., min_length=1, max_length=255)
    parent_span_id: str | None = None
    step_index: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    input_payload: dict[str, Any] | None = None
    output_payload: dict[str, Any] | None = None
    trace_id: str | None = None


class ProxyInterceptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    allowed: bool
    status: Literal["OK", "BLOCKED", "PENDING_APPROVAL", "LOOP_KILLED"]
    trace_id: str
    span_id: str
    reason: str | None = None


class SpanStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    span_id: str
    trace_id: str
    status: SpanStatus
    trace_status: TraceStatus
    guardrail_reason: str | None = None

class SpanCompleteRequest(BaseModel):
    """Post-execution results attached to a pre-flight span."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    output_payload: dict[str, Any] | None = None
    latency_ms: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)


class SpanCompleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    span_id: str
    trace_id: str
    span_status: SpanStatus
    trace_status: TraceStatus
