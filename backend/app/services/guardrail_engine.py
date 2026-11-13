"""Deterministic guardrail engine: cost, step-limit, regex blocking, HITL policies.

The engine is pure/CPU-bound and operates on immutable snapshots
(``TraceState`` / ``ServerPolicy``) so callers can evaluate it off the event
loop via ``asyncio.to_thread`` without touching an async SQLAlchemy session
from another thread.

Regex evaluation is hardened against ReDoS: patterns are length-capped,
nested-quantifier patterns are refused and treated as literals, the inspected
payload is truncated, and compiled patterns are cached.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from app.enums import PermissionMode, SpanStatus, SpanType, TraceStatus
from app.schemas import (
    MAX_BLOCKED_PATTERN_COUNT,
    MAX_BLOCKED_PATTERN_LENGTH,
    SpanIngestRequest,
)

# --- ReDoS / resource-exhaustion limits -------------------------------------
MAX_INSPECTION_CHARS = 20_000
_MAX_REGEX_CACHE = 256

# Nested quantifiers such as ``(a+)+`` or ``(.*)*`` are the classic
# catastrophic-backtracking shape. Those patterns are never compiled; they fall
# back to a literal substring check.
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[+*][^()]*\)\s*[+*]")


@dataclass(frozen=True)
class TraceState:
    """Immutable snapshot of the aggregate values the engine needs."""

    total_cost_usd: float = 0.0
    step_count: int = 0

    @classmethod
    def from_trace(cls, trace: Any) -> "TraceState":
        return cls(
            total_cost_usd=float(trace.total_cost_usd or 0.0),
            step_count=int(trace.step_count or 0),
        )


@dataclass(frozen=True)
class ServerPolicy:
    """Immutable snapshot of an MCP server's guardrail policy."""

    name: str
    permission_mode: PermissionMode
    max_cost_usd_per_run: float | None
    max_steps_per_run: int | None
    blocked_patterns: tuple[str, ...]

    @classmethod
    def from_server(cls, server: Any) -> "ServerPolicy | None":
        if server is None:
            return None
        raw_patterns = list(server.blocked_patterns or [])
        patterns = tuple(
            str(pattern)[:MAX_BLOCKED_PATTERN_LENGTH]
            for pattern in raw_patterns[:MAX_BLOCKED_PATTERN_COUNT]
            if str(pattern).strip()
        )
        mode = server.permission_mode
        if isinstance(mode, str):
            try:
                mode = PermissionMode(mode)
            except ValueError:
                mode = PermissionMode.ALLOW_ALL
        return cls(
            name=str(server.name),
            permission_mode=mode,
            max_cost_usd_per_run=(
                float(server.max_cost_usd_per_run)
                if server.max_cost_usd_per_run is not None
                else None
            ),
            max_steps_per_run=(
                int(server.max_steps_per_run)
                if server.max_steps_per_run is not None
                else None
            ),
            blocked_patterns=patterns,
        )


class GuardrailVerdict:
    def __init__(
        self,
        allowed: bool,
        span_status: SpanStatus,
        trace_status: TraceStatus | None = None,
        reason: str | None = None,
        blocked: bool = False,
    ):
        self.allowed = allowed
        self.span_status = span_status
        self.trace_status = trace_status
        self.reason = reason
        self.blocked = blocked


def _serialize_payload(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    try:
        return json.dumps(payload, default=str)
    except (TypeError, ValueError):
        return str(payload)


class GuardrailEngine:
    """Evaluates spans against MCP server guardrail rules."""

    def __init__(self) -> None:
        self._cache: dict[str, re.Pattern[str] | None] = {}

    def _compile(self, pattern: str) -> re.Pattern[str] | None:
        """Compile a pattern safely, refusing oversized/backtracking-prone input."""
        if pattern in self._cache:
            return self._cache[pattern]

        compiled: re.Pattern[str] | None = None
        if len(pattern) <= MAX_BLOCKED_PATTERN_LENGTH and not _NESTED_QUANTIFIER.search(
            pattern
        ):
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except (re.error, RecursionError):
                compiled = None

        if len(self._cache) >= _MAX_REGEX_CACHE:
            self._cache.clear()
        self._cache[pattern] = compiled
        return compiled

    def evaluate(self, span_request: SpanIngestRequest, trace: Any, server: Any) -> GuardrailVerdict:
        """Evaluate a span.

        ``trace`` may be an ``AgentTrace`` ORM object or a ``TraceState``;
        ``server`` may be an ``MCPServer`` ORM object, a ``ServerPolicy`` or
        ``None``.
        """
        state = trace if isinstance(trace, TraceState) else TraceState.from_trace(trace)
        policy = server if isinstance(server, ServerPolicy) else ServerPolicy.from_server(server)

        if policy is None:
            return GuardrailVerdict(
                allowed=True,
                span_status=SpanStatus.OK,
                trace_status=None,
                reason=None,
                blocked=False,
            )

        is_tool_call = span_request.span_type in (SpanType.MCP_TOOL_CALL, "MCP_TOOL_CALL")

        # 1. Cost limit check
        if policy.max_cost_usd_per_run is not None:
            projected_cost = state.total_cost_usd + float(span_request.cost_usd or 0.0)
            if projected_cost > policy.max_cost_usd_per_run:
                return GuardrailVerdict(
                    allowed=False,
                    span_status=SpanStatus.BLOCKED,
                    trace_status=TraceStatus.LOOP_KILLED,
                    reason=(
                        f"Cost limit exceeded: projected ${projected_cost:.4f} > "
                        f"max ${policy.max_cost_usd_per_run:.2f} per run"
                    ),
                    blocked=True,
                )

        # 2. Step limit check
        if policy.max_steps_per_run is not None:
            if state.step_count + 1 > policy.max_steps_per_run:
                return GuardrailVerdict(
                    allowed=False,
                    span_status=SpanStatus.BLOCKED,
                    trace_status=TraceStatus.LOOP_KILLED,
                    reason=(
                        f"Step limit exceeded: step {state.step_count + 1} > "
                        f"max {policy.max_steps_per_run} per run"
                    ),
                    blocked=True,
                )

        # 3. Blocked pattern check (bounded regex, literal fallback)
        if policy.blocked_patterns:
            serialized = (
                _serialize_payload(span_request.input_payload)
                + "\n"
                + _serialize_payload(span_request.output_payload)
            )[:MAX_INSPECTION_CHARS].lower()

            for pattern in policy.blocked_patterns:
                compiled = self._compile(pattern)
                if compiled is not None:
                    matched = compiled.search(serialized) is not None
                else:
                    matched = pattern.lower() in serialized
                if matched:
                    return GuardrailVerdict(
                        allowed=False,
                        span_status=SpanStatus.BLOCKED,
                        trace_status=None,
                        reason=f"Blocked pattern matched: '{pattern}'",
                        blocked=True,
                    )

        # 4. Deny-by-default permission modes
        if is_tool_call and policy.permission_mode == PermissionMode.STRICT_BLOCK:
            return GuardrailVerdict(
                allowed=False,
                span_status=SpanStatus.BLOCKED,
                trace_status=None,
                reason="STRICT_BLOCK policy: MCP tool calls are disabled",
                blocked=True,
            )
        if is_tool_call and policy.permission_mode == PermissionMode.READ_ONLY:
            return GuardrailVerdict(
                allowed=False,
                span_status=SpanStatus.BLOCKED,
                trace_status=None,
                reason="READ_ONLY policy: MCP tool calls are not permitted",
                blocked=True,
            )

        # 5. HITL requirement for MCP tool calls
        if is_tool_call and policy.permission_mode == PermissionMode.HITL_REQUIRED:
            return GuardrailVerdict(
                allowed=True,
                span_status=SpanStatus.PENDING_APPROVAL,
                trace_status=TraceStatus.PENDING_HITL,
                reason="HITL approval required for MCP tool call",
                blocked=False,
            )

        return GuardrailVerdict(
            allowed=True,
            span_status=SpanStatus.OK,
            trace_status=None,
            reason=None,
            blocked=False,
        )
