"""OpenTelemetry (OTLP/HTTP JSON) trace receiver.

Maps ``gen_ai.*`` semantic conventions and MCP attributes into AegisMCP traces
and spans so LangGraph, CrewAI, PydanticAI and the OpenAI Agents SDK can export
directly, without adopting the AegisMCP SDK.

Payload shape follows the OTLP JSON encoding:
``resourceSpans[].scopeSpans[].spans[]`` with typed attribute values.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import SpanStatus, SpanType, TraceStatus
from app.models import AgentTrace, TraceSpan
from app.services.events import sse_manager
from app.services.redactor import redact_mapping

logger = logging.getLogger(__name__)

_NANOS_PER_MS = 1_000_000

_LLM_OPERATIONS = {"chat", "text_completion", "generate_content", "embeddings", "invoke_agent"}
_TOOL_OPERATIONS = {"execute_tool", "execute_tools"}


def _attribute_value(value: Any) -> Any:
    """Decode one typed OTLP AnyValue."""
    if not isinstance(value, dict):
        return value
    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        try:
            return int(value["intValue"])
        except (TypeError, ValueError):
            return 0
    if "doubleValue" in value:
        try:
            return float(value["doubleValue"])
        except (TypeError, ValueError):
            return 0.0
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "arrayValue" in value:
        values = (value["arrayValue"] or {}).get("values") or []
        return [_attribute_value(item) for item in values]
    if "kvlistValue" in value:
        values = (value["kvlistValue"] or {}).get("values") or []
        return {
            str(item.get("key")): _attribute_value(item.get("value"))
            for item in values
            if isinstance(item, dict) and item.get("key") is not None
        }
    return None


def _attributes(attributes: Any) -> dict[str, Any]:
    """Convert an OTLP KeyValue list into a plain dict."""
    if not isinstance(attributes, list):
        return {}
    result: dict[str, Any] = {}
    for item in attributes:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key:
            continue
        result[key] = _attribute_value(item.get("value"))
    return result


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_ms(nanos: Any) -> int:
    value = _as_int(nanos, 0)
    return max(0, value // _NANOS_PER_MS)


def _span_type(attrs: dict[str, Any], name: str) -> SpanType:
    operation = str(attrs.get("gen_ai.operation.name") or "").lower()
    if "mcp.tool.name" in attrs or operation in _TOOL_OPERATIONS:
        return SpanType.MCP_TOOL_CALL
    if operation in _LLM_OPERATIONS:
        return SpanType.LLM_INFERENCE
    if "retriev" in name.lower() or "gen_ai.data_source.id" in attrs:
        return SpanType.RAG_RETRIEVAL
    return SpanType.LLM_INFERENCE


def _trace_id(otel_trace_id: Any) -> str:
    raw = str(otel_trace_id or "").strip()
    if raw:
        return f"trc_{raw[:24]}"
    return f"trc_otlp_{uuid.uuid4().hex[:8]}"


def _model_name(attrs: dict[str, Any]) -> str:
    for key in ("gen_ai.request.model", "gen_ai.response.model", "gen_ai.system"):
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:255]
    return "unknown"


def _payloads(attrs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    input_payload: dict[str, Any] = {}
    for key in (
        "gen_ai.prompt",
        "gen_ai.input.messages",
        "gen_ai.request.model",
        "gen_ai.request.temperature",
        "mcp.tool.name",
        "mcp.tool.arguments",
    ):
        if key in attrs and attrs[key] not in (None, ""):
            input_payload[key] = attrs[key]

    output_payload: dict[str, Any] = {}
    for key in (
        "gen_ai.completion",
        "gen_ai.output.messages",
        "gen_ai.response.finish_reasons",
        "mcp.tool.result",
    ):
        if key in attrs and attrs[key] not in (None, ""):
            output_payload[key] = attrs[key]

    if not input_payload:
        interesting = {
            key: value
            for key, value in attrs.items()
            if key.startswith(("gen_ai.", "mcp.")) and value not in (None, "")
        }
        if interesting:
            input_payload = {"attributes": interesting}
    return input_payload, output_payload


async def ingest_otlp(
    payload: Any, db: AsyncSession, operator: dict[str, Any]
) -> dict[str, Any]:
    """Persist an OTLP JSON trace payload and return the OTLP response body."""
    if not isinstance(payload, dict):
        raise ValueError("OTLP payload must be a JSON object")

    resource_spans = payload.get("resourceSpans")
    if not isinstance(resource_spans, list):
        raise ValueError("resourceSpans must be a list")

    org_id = operator.get("org_id") or settings.DEFAULT_ORG_ID
    requester = str(operator.get("sub") or "") or None
    accepted = 0
    rejected = 0
    budget = settings.OTLP_MAX_SPANS
    traces: dict[str, AgentTrace] = {}
    id_map: dict[str, str] = {}
    created: list[tuple[TraceSpan, str | None]] = []
    published: list[TraceSpan] = []

    for resource_span in resource_spans:
        if not isinstance(resource_span, dict):
            rejected += 1
            continue
        resource_attrs = _attributes((resource_span.get("resource") or {}).get("attributes"))
        agent_name = str(
            resource_attrs.get("service.name")
            or resource_attrs.get("service.namespace")
            or "otel-agent"
        )[:255]
        environment = str(
            resource_attrs.get("deployment.environment")
            or resource_attrs.get("deployment.environment.name")
            or "production"
        )[:100]

        scope_spans = resource_span.get("scopeSpans") or []
        if not isinstance(scope_spans, list):
            rejected += 1
            continue

        for scope_span in scope_spans:
            if not isinstance(scope_span, dict):
                rejected += 1
                continue
            spans = scope_span.get("spans") or []
            if not isinstance(spans, list):
                rejected += 1
                continue

            for otel_span in spans:
                if accepted >= budget:
                    rejected += 1
                    continue
                if not isinstance(otel_span, dict):
                    rejected += 1
                    continue

                attrs = _attributes(otel_span.get("attributes"))
                name = str(otel_span.get("name") or "otel-span")[:255]
                trace_key = _trace_id(otel_span.get("traceId"))
                local_span_id = f"spn_{uuid.uuid4().hex[:8]}"
                otel_span_id = str(otel_span.get("spanId") or "")
                if otel_span_id:
                    id_map[otel_span_id] = local_span_id

                model = _model_name(attrs)
                tool_name = attrs.get("mcp.tool.name")
                server_name = (
                    str(tool_name)[:255] if isinstance(tool_name, str) and tool_name
                    else model
                )

                trace = traces.get(trace_key)
                if trace is None:
                    result = await db.execute(
                        select(AgentTrace).where(
                            AgentTrace.id == trace_key, AgentTrace.org_id == org_id
                        )
                    )
                    trace = result.scalar_one_or_none()
                    if trace is None:
                        foreign = await db.execute(
                            select(AgentTrace.id).where(AgentTrace.id == trace_key)
                        )
                        if foreign.scalar_one_or_none() is not None:
                            rejected += 1
                            continue
                        trace = AgentTrace(
                            id=trace_key,
                            agent_name=agent_name,
                            environment=environment,
                            org_id=org_id,
                            status=TraceStatus.COMPLETED,
                            total_tokens=0,
                            prompt_tokens=0,
                            completion_tokens=0,
                            total_cost_usd=0.0,
                            total_latency_ms=0,
                            step_count=0,
                        )
                        db.add(trace)
                        await db.flush()
                    traces[trace_key] = trace

                input_tokens = _as_int(
                    attrs.get("gen_ai.usage.input_tokens")
                    or attrs.get("gen_ai.usage.prompt_tokens")
                )
                output_tokens = _as_int(
                    attrs.get("gen_ai.usage.output_tokens")
                    or attrs.get("gen_ai.usage.completion_tokens")
                )
                total_tokens = _as_int(
                    attrs.get("gen_ai.usage.total_tokens"), input_tokens + output_tokens
                )
                cost = _as_float(
                    attrs.get("gen_ai.usage.total_cost")
                    or attrs.get("gen_ai.usage.cost_usd")
                )
                latency_ms = max(
                    0,
                    _to_ms(otel_span.get("endTimeUnixNano"))
                    - _to_ms(otel_span.get("startTimeUnixNano")),
                )

                status_code = _as_int((otel_span.get("status") or {}).get("code"), 0)
                span_status = SpanStatus.ERROR if status_code == 2 else SpanStatus.OK

                input_payload, output_payload = _payloads(attrs)
                safe_input, report = redact_mapping(input_payload)
                safe_output, output_report = redact_mapping(output_payload)
                report.extend(output_report)
                reason = report.summary()

                span = TraceSpan(
                    id=local_span_id,
                    trace_id=trace_key,
                    parent_span_id=None,
                    step_index=trace.step_count or 0,
                    span_type=_span_type(attrs, name),
                    name=name,
                    model_or_server=server_name,
                    status=span_status,
                    latency_ms=latency_ms,
                    tokens_used=total_tokens,
                    cost_usd=cost,
                    input_payload=safe_input,
                    output_payload=safe_output,
                    guardrail_reason=reason,
                    requester_id=requester,
                )
                db.add(span)
                created.append((span, str(otel_span.get("parentSpanId") or "") or None))
                published.append(span)

                trace.total_tokens = (trace.total_tokens or 0) + total_tokens
                trace.prompt_tokens = (trace.prompt_tokens or 0) + input_tokens
                trace.completion_tokens = (trace.completion_tokens or 0) + output_tokens
                trace.total_cost_usd = round((trace.total_cost_usd or 0.0) + cost, 6)
                trace.total_latency_ms = (trace.total_latency_ms or 0) + latency_ms
                trace.step_count = (trace.step_count or 0) + 1
                accepted += 1

    for span, parent_otel_id in created:
        if parent_otel_id and parent_otel_id in id_map:
            span.parent_span_id = id_map[parent_otel_id]

    for trace in traces.values():
        trace.status = TraceStatus.COMPLETED
        trace.ended_at = trace.ended_at or datetime.now(timezone.utc)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    for span in published:
        await sse_manager.publish(
            {
                "type": "span_ingested",
                "trace_id": span.trace_id,
                "span_id": span.id,
                "span_status": span.status.value,
                "span_name": span.name,
                "trace_status": "COMPLETED",
            }
        )

    response: dict[str, Any] = {"partialSuccess": {}}
    if rejected:
        response["partialSuccess"] = {
            "rejectedSpans": rejected,
            "errorMessage": "Some spans were rejected (limit reached, malformed, or foreign trace)",
        }
    logger.info("OTLP ingest accepted=%d rejected=%d", accepted, rejected)
    return response
