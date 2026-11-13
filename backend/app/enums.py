"""Shared enumeration types for AegisMCP."""

from enum import Enum as PyEnum


class TransportType(str, PyEnum):
    STDIO = "stdio"
    SSE = "sse"
    WEBSOCKET = "websocket"


class ServerStatus(str, PyEnum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


class PermissionMode(str, PyEnum):
    ALLOW_ALL = "ALLOW_ALL"
    READ_ONLY = "READ_ONLY"
    HITL_REQUIRED = "HITL_REQUIRED"
    STRICT_BLOCK = "STRICT_BLOCK"


class TraceStatus(str, PyEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    PENDING_HITL = "PENDING_HITL"
    LOOP_KILLED = "LOOP_KILLED"


class SpanType(str, PyEnum):
    LLM_INFERENCE = "LLM_INFERENCE"
    MCP_TOOL_CALL = "MCP_TOOL_CALL"
    RAG_RETRIEVAL = "RAG_RETRIEVAL"
    GUARDRAIL_INTERCEPT = "GUARDRAIL_INTERCEPT"


class SpanStatus(str, PyEnum):
    OK = "OK"
    BLOCKED = "BLOCKED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ERROR = "ERROR"
