"""Protocol-aware MCP JSON-RPC 2.0 gateway.

Agents point their MCP client at ``POST /api/v1/mcp/{server_name}/rpc`` and this
module speaks the protocol back, so policies apply even when the agent never
imports the AegisMCP SDK:

* ``tools/list`` - pins the canonical tool manifest (OWASP MCP03) and rejects
  poisoned descriptions or a silently mutated manifest (rug pull).
* ``tools/call`` - evaluates guardrails before the upstream server is invoked,
  pauses HITL calls, and screens/redacts the tool output on the way back.

Upstream servers are forwarded over HTTP. Seeded demo servers (``.internal`` or
``demo://`` endpoints) are served by a deterministic in-process catalog so the
gateway works offline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import SpanStatus, SpanType, TraceStatus
from app.models import AgentTrace, MCPServer, TraceSpan
from app.schemas import SpanIngestRequest
from app.services.events import sse_manager
from app.services.guardrail_engine import (
    GuardrailEngine,
    GuardrailVerdict,
    ServerPolicy,
    TraceState,
)
from app.services.mcp_catalog import (
    canonical_tools,
    demo_tool_output,
    get_demo_catalog,
    is_demo_server,
    manifest_hash,
    scan_tool_descriptions,
    scan_tool_output,
)
from app.services.redactor import redact_mapping

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSIONS = ("2026-07-28", "2025-06-18")
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

BLOCKED_ERROR = -32001
LOOP_KILLED_ERROR = -32002
PENDING_APPROVAL_ERROR = -32003
TOOL_POISONED_ERROR = -32004
MANIFEST_CHANGED_ERROR = -32005
OUTPUT_INJECTION_ERROR = -32006


class UpstreamError(RuntimeError):
    """The upstream MCP server could not serve a request."""


class TenantMismatch(RuntimeError):
    """The requested trace belongs to another organization."""


@dataclass
class UpstreamReply:
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


def _ok(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _err(
    request_id: Any, code: int, message: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


async def _post_upstream(
    server: MCPServer, method: str, params: dict[str, Any], request_id: Any
) -> UpstreamReply:
    """Forward one JSON-RPC request to a real upstream MCP server."""
    payload = {
        "jsonrpc": "2.0",
        "id": request_id if request_id is not None else f"aegis-{uuid.uuid4().hex[:8]}",
        "method": method,
        "params": params,
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.MCP_UPSTREAM_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(
                server.endpoint_url,
                json=payload,
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise UpstreamError(f"upstream request failed: {exc}") from exc

    if response.status_code >= 400:
        raise UpstreamError(f"upstream returned HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError as exc:
        raise UpstreamError("upstream returned a non-JSON body") from exc

    if not isinstance(data, dict):
        raise UpstreamError("upstream returned a malformed JSON-RPC envelope")
    if isinstance(data.get("error"), dict):
        return UpstreamReply(error=data["error"])
    result = data.get("result")
    return UpstreamReply(result=result if isinstance(result, dict) else {})


async def _fetch_tools(server: MCPServer) -> list[dict[str, Any]]:
    if is_demo_server(server.endpoint_url):
        return get_demo_catalog(server.name)
    reply = await _post_upstream(server, "tools/list", {}, None)
    if reply.error:
        raise UpstreamError(str(reply.error.get("message") or "tools/list failed"))
    tools = (reply.result or {}).get("tools") or []
    return [tool for tool in tools if isinstance(tool, dict)]


async def _invoke_tool(
    server: MCPServer, tool_name: str, arguments: dict[str, Any], request_id: Any
) -> dict[str, Any]:
    if is_demo_server(server.endpoint_url):
        return demo_tool_output(server.name, tool_name, arguments)
    reply = await _post_upstream(
        server,
        "tools/call",
        {"name": tool_name, "arguments": arguments},
        request_id,
    )
    if reply.error:
        raise UpstreamError(str(reply.error.get("message") or "tools/call failed"))
    return reply.result or {}


async def _next_step_index(db: AsyncSession, trace_id: str) -> int:
    count = await db.execute(
        select(func.count(TraceSpan.id)).where(TraceSpan.trace_id == trace_id)
    )
    return int(count.scalar() or 0)


async def _resolve_trace(
    db: AsyncSession,
    operator: dict[str, Any],
    server: MCPServer,
    params: dict[str, Any],
    manifest: bool = False,
) -> AgentTrace:
    """Find or create the trace for this MCP session, scoped to the caller's org."""
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    org_id = operator.get("org_id") or settings.DEFAULT_ORG_ID
    default_trace_id = (
        f"trc_manifest_{server.id.replace('-', '')[:12]}"
        if manifest
        else f"trc_mcp_{uuid.uuid4().hex[:8]}"
    )
    trace_id = str(meta.get("aegis_trace_id") or default_trace_id)

    result = await db.execute(
        select(AgentTrace).where(
            AgentTrace.id == trace_id, AgentTrace.org_id == org_id
        )
    )
    trace = result.scalar_one_or_none()
    if trace:
        return trace

    existing = await db.execute(select(AgentTrace.id).where(AgentTrace.id == trace_id))
    if existing.scalar_one_or_none() is not None:
        raise TenantMismatch("Trace belongs to another organization")

    default_agent = (
        f"mcp-manifest-{server.name}" if manifest else "mcp-gateway-client"
    )
    trace = AgentTrace(
        id=trace_id,
        agent_name=str(meta.get("agent_name") or default_agent)[:255],
        environment=str(meta.get("environment") or "production")[:100],
        org_id=org_id,
        status=TraceStatus.COMPLETED if manifest else TraceStatus.RUNNING,
        total_tokens=0,
        prompt_tokens=0,
        completion_tokens=0,
        total_cost_usd=0.0,
        total_latency_ms=0,
        step_count=0,
        mcp_server_id=server.id,
        ended_at=datetime.now(timezone.utc) if manifest else None,
    )
    db.add(trace)
    await db.flush()
    return trace


async def _record_span(
    db: AsyncSession,
    *,
    trace: AgentTrace,
    server: MCPServer,
    name: str,
    status: SpanStatus,
    reason: str | None,
    input_payload: dict[str, Any] | None,
    requester: str | None,
    span_type: SpanType = SpanType.MCP_TOOL_CALL,
    output_payload: dict[str, Any] | None = None,
    latency_ms: int = 0,
    tokens_used: int = 0,
    cost_usd: float = 0.0,
) -> TraceSpan:
    """Persist a redacted span and fold its usage into the trace aggregates."""
    redacted_input, report = redact_mapping(input_payload)
    redacted_output, output_report = redact_mapping(output_payload)
    report.extend(output_report)
    if report.summary():
        reason = f"{reason} | {report.summary()}" if reason else report.summary()

    span = TraceSpan(
        trace_id=trace.id,
        parent_span_id=None,
        step_index=await _next_step_index(db, trace.id),
        span_type=span_type,
        name=name[:255],
        model_or_server=server.name,
        status=status,
        latency_ms=max(0, latency_ms),
        tokens_used=max(0, tokens_used),
        cost_usd=max(0.0, cost_usd),
        input_payload=redacted_input,
        output_payload=redacted_output,
        guardrail_reason=reason,
        requester_id=requester,
    )
    db.add(span)

    trace.total_tokens = (trace.total_tokens or 0) + max(0, tokens_used)
    half = max(0, tokens_used) // 2
    trace.prompt_tokens = (trace.prompt_tokens or 0) + half
    trace.completion_tokens = (trace.completion_tokens or 0) + (max(0, tokens_used) - half)
    trace.total_cost_usd = round((trace.total_cost_usd or 0.0) + max(0.0, cost_usd), 6)
    trace.total_latency_ms = (trace.total_latency_ms or 0) + max(0, latency_ms)
    trace.step_count = (trace.step_count or 0) + 1

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(span)

    await sse_manager.publish(
        {
            "type": "span_ingested",
            "trace_id": trace.id,
            "span_id": span.id,
            "trace_status": trace.status.value,
            "span_status": span.status.value,
            "blocked": status in (SpanStatus.BLOCKED, SpanStatus.ERROR),
        }
    )
    return span


def _initialize_result(params: dict[str, Any]) -> dict[str, Any]:
    """Negotiate the protocol version and advertise AegisMCP capabilities."""
    requested = params.get("protocolVersion")
    version = (
        requested
        if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS
        else DEFAULT_PROTOCOL_VERSION
    )
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": True}, "logging": {}},
        "serverInfo": {"name": "AegisMCP Gateway", "version": "1.0.0"},
        "instructions": (
            "Guarded MCP gateway: tool manifests are pinned on first discovery and "
            "every tools/call is policy-checked before the upstream server runs it."
        ),
    }


async def _tools_list(
    server: MCPServer,
    request_id: Any,
    params: dict[str, Any],
    db: AsyncSession,
    operator: dict[str, Any],
    requester: str | None,
) -> dict[str, Any]:
    """Return the upstream catalog after OWASP MCP03 pinning and scanning."""
    try:
        tools = await _fetch_tools(server)
    except UpstreamError as exc:
        return _err(request_id, INTERNAL_ERROR, f"Upstream MCP server unavailable: {exc}")

    canonical = canonical_tools(tools)
    digest = manifest_hash(canonical)
    trace = await _resolve_trace(db, operator, server, params, manifest=True)

    findings = scan_tool_descriptions(canonical)
    if findings:
        reason = "OWASP_MCP03_TOOL_POISONING: " + "; ".join(findings[:5])
        span = await _record_span(
            db,
            trace=trace,
            server=server,
            name=f"mcp:{server.name}:tools/list",
            status=SpanStatus.BLOCKED,
            reason=reason,
            input_payload={"tool_manifest_hash": digest, "findings": findings[:5]},
            requester=requester,
            span_type=SpanType.GUARDRAIL_INTERCEPT,
        )
        return _err(
            request_id,
            TOOL_POISONED_ERROR,
            "Tool manifest rejected: hidden instructions in tool metadata",
            {
                "aegis_status": "BLOCKED",
                "trace_id": trace.id,
                "span_id": span.id,
                "findings": findings[:5],
            },
        )

    if server.tool_manifest_hash is None:
        server.tool_manifest_hash = digest
        server.pinned_tools = canonical
        await db.commit()
        await _record_span(
            db,
            trace=trace,
            server=server,
            name=f"mcp:{server.name}:tools/list",
            status=SpanStatus.OK,
            reason=f"OWASP_MCP03: pinned tool manifest {digest[:12]}",
            input_payload={"tools": [tool["name"] for tool in canonical]},
            requester=requester,
            span_type=SpanType.GUARDRAIL_INTERCEPT,
        )
        return _ok(request_id, {"tools": tools})

    if server.tool_manifest_hash != digest:
        reason = "OWASP_MCP03_RUG_PULL_DETECTED: Tool manifest hash mismatch"
        span = await _record_span(
            db,
            trace=trace,
            server=server,
            name=f"mcp:{server.name}:tools/list",
            status=SpanStatus.BLOCKED,
            reason=reason,
            input_payload={
                "pinned_hash": server.tool_manifest_hash,
                "observed_hash": digest,
            },
            requester=requester,
            span_type=SpanType.GUARDRAIL_INTERCEPT,
        )
        return _err(
            request_id,
            MANIFEST_CHANGED_ERROR,
            reason + "; reset the pinned manifest to accept the new catalog",
            {
                "aegis_status": "BLOCKED",
                "trace_id": trace.id,
                "span_id": span.id,
                "pinned_hash": server.tool_manifest_hash,
                "observed_hash": digest,
            },
        )

    return _ok(request_id, {"tools": tools})


async def _tools_call(
    server: MCPServer,
    request_id: Any,
    params: dict[str, Any],
    db: AsyncSession,
    operator: dict[str, Any],
    requester: str | None,
) -> dict[str, Any]:
    """Authorise, execute and screen one MCP tool call."""
    tool_name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(tool_name, str) or not tool_name:
        return _err(request_id, INVALID_PARAMS, "tools/call requires params.name")
    if not isinstance(arguments, dict):
        return _err(request_id, INVALID_PARAMS, "tools/call params.arguments must be an object")

    trace = await _resolve_trace(db, operator, server, params)
    span_name = f"mcp:{server.name}:{tool_name}"
    invocation = {"tool": tool_name, "arguments": arguments}

    if trace.status == TraceStatus.LOOP_KILLED:
        return _err(
            request_id,
            LOOP_KILLED_ERROR,
            "Trace was terminated by the loop guard",
            {"aegis_status": "LOOP_KILLED", "trace_id": trace.id},
        )

    span_request = SpanIngestRequest(
        trace_id=trace.id,
        agent_name=trace.agent_name,
        environment=trace.environment,
        span_type=SpanType.MCP_TOOL_CALL,
        name=span_name,
        model_or_server=server.name,
        step_index=await _next_step_index(db, trace.id),
        input_payload=invocation,
    )
    engine = GuardrailEngine()
    verdict: GuardrailVerdict = await asyncio.to_thread(
        engine.evaluate,
        span_request,
        TraceState.from_trace(trace),
        ServerPolicy.from_server(server),
    )

    if verdict.span_status == SpanStatus.BLOCKED:
        if verdict.trace_status:
            trace.status = verdict.trace_status
        span = await _record_span(
            db,
            trace=trace,
            server=server,
            name=span_name,
            status=SpanStatus.BLOCKED,
            reason=verdict.reason,
            input_payload=invocation,
            requester=requester,
        )
        loop_killed = verdict.trace_status == TraceStatus.LOOP_KILLED
        return _err(
            request_id,
            LOOP_KILLED_ERROR if loop_killed else BLOCKED_ERROR,
            verdict.reason or "Blocked by guardrails",
            {
                "aegis_status": "LOOP_KILLED" if loop_killed else "BLOCKED",
                "trace_id": trace.id,
                "span_id": span.id,
                "reason": verdict.reason,
            },
        )

    if verdict.span_status == SpanStatus.PENDING_APPROVAL:
        trace.status = TraceStatus.PENDING_HITL
        span = await _record_span(
            db,
            trace=trace,
            server=server,
            name=span_name,
            status=SpanStatus.PENDING_APPROVAL,
            reason=verdict.reason,
            input_payload=invocation,
            requester=requester,
        )
        return _err(
            request_id,
            PENDING_APPROVAL_ERROR,
            "Human approval required before this tool call executes",
            {
                "aegis_status": "PENDING_APPROVAL",
                "trace_id": trace.id,
                "span_id": span.id,
                "poll": f"/api/v1/spans/{span.id}/status",
            },
        )

    started = time.perf_counter()
    try:
        output = await _invoke_tool(server, tool_name, arguments, request_id)
    except UpstreamError as exc:
        span = await _record_span(
            db,
            trace=trace,
            server=server,
            name=span_name,
            status=SpanStatus.ERROR,
            reason=f"Upstream MCP failure: {exc}",
            input_payload=invocation,
            requester=requester,
        )
        return _err(
            request_id,
            INTERNAL_ERROR,
            str(exc),
            {"trace_id": trace.id, "span_id": span.id},
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    safe_output, _ = redact_mapping(output)
    serialised = json.dumps(safe_output, default=str)
    injection = scan_tool_output(serialised)
    if injection:
        span = await _record_span(
            db,
            trace=trace,
            server=server,
            name=span_name,
            status=SpanStatus.BLOCKED,
            reason="OWASP_MCP03_OUTPUT_INJECTION: " + "; ".join(injection[:5]),
            input_payload=invocation,
            output_payload=safe_output,
            latency_ms=latency_ms,
            requester=requester,
        )
        return _err(
            request_id,
            OUTPUT_INJECTION_ERROR,
            "Tool output rejected: suspected indirect prompt injection",
            {
                "aegis_status": "BLOCKED",
                "trace_id": trace.id,
                "span_id": span.id,
                "findings": injection[:5],
            },
        )

    span = await _record_span(
        db,
        trace=trace,
        server=server,
        name=span_name,
        status=SpanStatus.OK,
        reason=None,
        input_payload=invocation,
        output_payload=safe_output,
        latency_ms=latency_ms,
        requester=requester,
    )
    return _ok(
        request_id,
        {
            "content": [{"type": "text", "text": serialised}],
            "structuredContent": safe_output,
            "isError": False,
            "_aegis": {"trace_id": trace.id, "span_id": span.id},
        },
    )


async def handle_rpc(
    *,
    server: MCPServer,
    payload: Any,
    db: AsyncSession,
    operator: dict[str, Any],
) -> dict[str, Any] | None:
    """Dispatch one JSON-RPC 2.0 message and return the response envelope."""
    if not isinstance(payload, dict):
        return _err(None, INVALID_REQUEST, "Invalid Request: expected a JSON object")

    request_id = payload.get("id")
    method = payload.get("method")
    if payload.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _err(request_id, INVALID_REQUEST, "Invalid Request: expected JSON-RPC 2.0")

    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _err(request_id, INVALID_PARAMS, "params must be an object")

    if method.startswith("notifications/"):
        return None

    requester = str(operator.get("sub") or "") or None
    try:
        if method == "initialize":
            return _ok(request_id, _initialize_result(params))
        if method == "ping":
            return _ok(request_id, {})
        if method == "tools/list":
            return await _tools_list(server, request_id, params, db, operator, requester)
        if method == "tools/call":
            return await _tools_call(server, request_id, params, db, operator, requester)
    except TenantMismatch:
        raise
    except Exception:  # noqa: BLE001 - returned as a JSON-RPC internal error
        logger.exception("MCP gateway failure for method %s", method)
        return _err(request_id, INTERNAL_ERROR, "Internal gateway error")
    return _err(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
