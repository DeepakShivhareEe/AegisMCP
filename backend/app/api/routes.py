"""REST & SSE API routes for AegisMCP."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Body,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.enums import SpanStatus, TraceStatus
from app.models import AgentTrace, APIKey, MCPServer, TraceSpan
from app.schemas import (
    AgentTraceResponse,
    AnalyticsSummary,
    APIKeyCreate,
    APIKeyCreateResponse,
    APIKeyResponse,
    HealthResponse,
    HitlPendingItem,
    HitlPendingResponse,
    MCPServerResponse,
    MCPServerUpdate,
    MeResponse,
    ProxyInterceptRequest,
    ProxyInterceptResponse,
    SessionCreateRequest,
    SessionResponse,
    SimulatorTriggerRequest,
    SimulatorTriggerResponse,
    SpanDecisionRequest,
    SpanCompleteRequest,
    SpanCompleteResponse,
    SpanDecisionResponse,
    SpanIngestRequest,
    SpanIngestResponse,
    SpanStatusResponse,
    TraceDetailResponse,
    TraceSpanResponse,
)
from app.security import (
    cookie_security_flags,
    generate_api_key,
    generate_csrf_token,
    mint_session_token,
    rate_limit_service,
    rate_limiter,
    verify_api_key,
    verify_api_key_db,
    verify_bootstrap_token,
    verify_csrf_double_submit,
    verify_session_token,
)
from app.services.guardrail_engine import GuardrailEngine, ServerPolicy, TraceState
from app.services.events import sse_manager
from app.services.mcp_proxy import TenantMismatch
from app.services.mcp_proxy import handle_rpc as handle_mcp_rpc
from app.services.otlp import ingest_otlp
from app.services.redactor import redact_mapping
from app.services.simulator import TraceSimulator

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers & dependencies
# ---------------------------------------------------------------------------

def _operator_org(operator: dict[str, Any]) -> str:
    """Resolve the tenant for an authenticated principal."""
    org_id = operator.get("org_id")
    return org_id if isinstance(org_id, str) and org_id else settings.DEFAULT_ORG_ID


async def _api_key_principal(
    db: AsyncSession,
    x_aegis_api_key: str | None,
    authorization: str | None = None,
) -> dict[str, Any] | None:
    """Resolve a machine principal from X-Aegis-API-Key or a Bearer token."""
    candidate = (x_aegis_api_key or "").strip()
    if not candidate and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            candidate = value.strip()
    if not candidate:
        return None

    operator = await verify_api_key_db(candidate, db)
    if operator:
        return operator
    if verify_api_key(candidate):
        return {
            "sub": "machine",
            "org_id": settings.DEFAULT_ORG_ID,
            "role": "admin",
            "auth_type": "api_key",
        }
    return None


def _apply_trace_aggregates(
    trace: AgentTrace,
    *,
    tokens_used: int,
    cost_usd: float,
    latency_ms: int,
) -> None:
    """Fold one span's usage into its parent trace's running totals."""
    tokens = tokens_used or 0
    trace.total_tokens = (trace.total_tokens or 0) + tokens
    trace.prompt_tokens = (trace.prompt_tokens or 0) + (tokens // 2)
    trace.completion_tokens = (trace.completion_tokens or 0) + (tokens - (tokens // 2))
    trace.total_cost_usd = round((trace.total_cost_usd or 0.0) + (cost_usd or 0.0), 6)
    trace.total_latency_ms = (trace.total_latency_ms or 0) + (latency_ms or 0)
    trace.step_count = (trace.step_count or 0) + 1


async def _safe_commit(db: AsyncSession) -> None:
    """Commit or roll back, converting driver failures into a clean 500."""
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - surfaced as a sanitized 500
        await db.rollback()
        logger.exception("Database commit failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database transaction failed",
        ) from exc


async def _evaluate_guardrail(
    span_request: SpanIngestRequest,
    trace: AgentTrace,
    server: MCPServer | None,
):
    """Run the CPU-bound guardrail engine off the ASGI event loop."""
    engine = GuardrailEngine()
    state = TraceState.from_trace(trace)
    policy = ServerPolicy.from_server(server)
    return await asyncio.to_thread(engine.evaluate, span_request, state, policy)


async def get_current_operator(
    aegis_session: Annotated[str | None, Cookie()] = None,
    x_aegis_api_key: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> dict[str, Any] | None:
    """Resolve the current operator from API key or session cookie."""
    if x_aegis_api_key:
        operator = await verify_api_key_db(x_aegis_api_key, db)
        if operator:
            return operator
        if verify_api_key(x_aegis_api_key):
            return {
                "sub": "machine",
                "org_id": settings.DEFAULT_ORG_ID,
                "role": "admin",
                "auth_type": "api_key",
            }
        # An explicitly presented credential that fails must not silently fall
        # back to a cookie session: that would mask a misconfigured client.
        return None

    if aegis_session:
        payload = verify_session_token(aegis_session)
        if payload:
            return payload

    return None


async def require_operator(
    operator: Annotated[dict[str, Any] | None, Depends(get_current_operator)],
) -> dict[str, Any]:
    """Require a valid operator session or API key."""
    if not operator:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return operator


async def require_admin(
    operator: Annotated[dict[str, Any], Depends(require_operator)],
) -> dict[str, Any]:
    """Restrict a mutation to admins; auditors are read-only."""
    if operator.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role: admin required",
        )
    return operator


async def csrf_protect(
    request: Request,
    operator: Annotated[dict[str, Any] | None, Depends(get_current_operator)],
    aegis_csrf: Annotated[str | None, Cookie()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> None:
    """Enforce double-submit CSRF on mutating browser requests.

    The session bootstrap path is exempt because it creates the session and
    CSRF pair itself. API-key callers are machine-to-machine and exempt.
    """
    if request.method not in ("POST", "PATCH", "DELETE"):
        return

    if request.url.path == "/api/v1/auth/session":
        return

    if not operator:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    if operator.get("auth_type") == "api_key":
        return

    if not verify_csrf_double_submit(aegis_csrf, x_csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token mismatch",
        )


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@router.post("/auth/session", response_model=SessionResponse)
async def auth_session(
    response: Response,
    session_request: SessionCreateRequest,
    x_aegis_bootstrap_token: Annotated[str | None, Header()] = None,
) -> SessionResponse:
    """Mint aegis_session (HttpOnly JWT) + aegis_csrf cookies."""
    if not verify_bootstrap_token(x_aegis_bootstrap_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing bootstrap token",
        )

    if not settings.ALLOW_SESSION_BOOTSTRAP:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session bootstrap is disabled; authenticate through the identity provider",
        )

    org_id = session_request.org_id
    if org_id not in settings.ALLOWED_ORG_IDS:
        logger.warning(
            "Rejecting session request for unknown org_id=%s; clamping to %s",
            org_id,
            settings.DEFAULT_ORG_ID,
        )
        org_id = settings.DEFAULT_ORG_ID

    token = mint_session_token(
        session_request.operator_id,
        org_id,
        session_request.role,
    )
    csrf_token = generate_csrf_token()

    cookie_flags = cookie_security_flags()

    response.set_cookie(
        key="aegis_session",
        value=token,
        httponly=True,
        samesite=cookie_flags["samesite"],
        secure=cookie_flags["secure"],
        path="/",
        max_age=settings.JWT_EXPIRATION_MINUTES * 60,
    )
    response.set_cookie(
        key="aegis_csrf",
        value=csrf_token,
        httponly=False,
        samesite=cookie_flags["samesite"],
        secure=cookie_flags["secure"],
        path="/",
        max_age=settings.JWT_EXPIRATION_MINUTES * 60,
    )

    return SessionResponse(
        operator_id=session_request.operator_id,
        org_id=org_id,
        role=session_request.role,
        expires_in=settings.JWT_EXPIRATION_MINUTES * 60,
    )


@router.get("/auth/me", response_model=MeResponse)
async def auth_me(
    request: Request,
    operator: Annotated[dict[str, Any] | None, Depends(get_current_operator)],
    aegis_csrf: Annotated[str | None, Cookie()] = None,
) -> MeResponse:
    """Return the active operator session & security status."""
    if not operator:
        return MeResponse(authenticated=False, csrf_active=False)

    client_id = str(operator.get("sub") or (request.client.host if request.client else "unknown"))
    return MeResponse(
        authenticated=True,
        operator_id=operator.get("sub"),
        org_id=operator.get("org_id"),
        role=operator.get("role"),
        csrf_active=bool(aegis_csrf),
        rate_limit_remaining=await rate_limit_service.remaining(client_id),
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
async def health(db: Annotated[AsyncSession, Depends(get_db)]) -> HealthResponse:
    """System health & DB status."""
    try:
        await db.execute(select(func.count()).select_from(MCPServer))
        db_status = "connected"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Database health check failed: %s", exc)
        db_status = "disconnected"
    return HealthResponse(status="ok", database=db_status)


@router.get("/models")
async def list_models() -> dict[str, Any]:
    """OpenAI-compatible models endpoint for SDK auto-discovery."""
    return {"data": [], "object": "list"}


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------

@router.get("/traces", response_model=list[AgentTraceResponse])
async def list_traces(
    operator: Annotated[dict[str, Any], Depends(require_operator)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: TraceStatus | None = None,
    agent_name: Annotated[str | None, Query(max_length=255)] = None,
    search: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Any:
    """List traces for the caller's organization with optional filtering."""
    org_id = _operator_org(operator)
    conditions = [AgentTrace.org_id == org_id]
    if status:
        conditions.append(AgentTrace.status == status)
    if agent_name:
        conditions.append(AgentTrace.agent_name.icontains(agent_name, autoescape=True))
    if search:
        conditions.append(AgentTrace.agent_name.icontains(search, autoescape=True))

    query = (
        select(AgentTrace)
        .where(and_(*conditions))
        .order_by(desc(AgentTrace.started_at))
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/traces/{trace_id}", response_model=TraceDetailResponse)
async def get_trace(
    trace_id: str,
    operator: Annotated[dict[str, Any], Depends(require_operator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TraceDetailResponse:
    """Return trace metadata + ordered spans, scoped to the caller's org."""
    org_id = _operator_org(operator)
    result = await db.execute(
        select(AgentTrace).where(
            AgentTrace.id == trace_id,
            AgentTrace.org_id == org_id,
        )
    )
    trace = result.scalar_one_or_none()
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans_result = await db.execute(
        select(TraceSpan)
        .where(TraceSpan.trace_id == trace_id)
        .order_by(TraceSpan.step_index)
    )
    spans = spans_result.scalars().all()

    return TraceDetailResponse(
        trace=AgentTraceResponse.model_validate(trace),
        spans=[TraceSpanResponse.model_validate(span) for span in spans],
    )


# ---------------------------------------------------------------------------
# MCP Servers
# ---------------------------------------------------------------------------

@router.get("/mcp-servers", response_model=list[MCPServerResponse])
async def list_mcp_servers(
    operator: Annotated[dict[str, Any], Depends(require_operator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """List registered MCP servers (deployment-wide policy configuration)."""
    result = await db.execute(select(MCPServer).order_by(MCPServer.name))
    return result.scalars().all()


@router.patch(
    "/mcp-servers/{server_id}",
    response_model=MCPServerResponse,
    dependencies=[Depends(csrf_protect)],
)
async def patch_mcp_server(
    server_id: str,
    update: MCPServerUpdate,
    operator: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MCPServer:
    """Update an MCP server's security policy."""
    result = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    update_data = update.model_dump(exclude_unset=True, exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=422, detail="No policy fields supplied")

    for field, value in update_data.items():
        setattr(server, field, value)

    await _safe_commit(db)
    await db.refresh(server)
    return server


# ---------------------------------------------------------------------------
# Span Ingest
# ---------------------------------------------------------------------------

@router.post(
    "/ingest/span",
    response_model=SpanIngestResponse,
    dependencies=[Depends(csrf_protect)],
)
async def ingest_span(
    span_request: SpanIngestRequest,
    operator: Annotated[dict[str, Any], Depends(require_operator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SpanIngestResponse:
    """Record a span, evaluate guardrails and update trace aggregates."""
    org_id = _operator_org(operator)

    result = await db.execute(
        select(AgentTrace).where(
            AgentTrace.id == span_request.trace_id,
            AgentTrace.org_id == org_id,
        )
    )
    trace = result.scalar_one_or_none()

    if not trace:
        # Distinguish "unknown trace" from "another tenant's trace" without
        # leaking which one it is to the caller.
        existing = await db.execute(
            select(AgentTrace.id).where(AgentTrace.id == span_request.trace_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=404, detail="Trace not found")

        trace = AgentTrace(
            id=span_request.trace_id,
            agent_name=span_request.agent_name,
            environment=span_request.environment,
            org_id=org_id,
            status=TraceStatus.RUNNING,
            total_tokens=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_cost_usd=0.0,
            total_latency_ms=0,
            step_count=0,
        )
        db.add(trace)
        await db.flush()

    if trace.status == TraceStatus.LOOP_KILLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Trace was terminated by the loop guard and accepts no further spans",
        )

    server_result = await db.execute(
        select(MCPServer).where(MCPServer.name == span_request.model_or_server)
    )
    server = server_result.scalar_one_or_none()

    verdict = await _evaluate_guardrail(span_request, trace, server)

    safe_input, redaction = redact_mapping(span_request.input_payload)
    safe_output, output_redaction = redact_mapping(span_request.output_payload)
    redaction.extend(output_redaction)
    reason = verdict.reason
    if redaction.summary():
        reason = f"{reason} | {redaction.summary()}" if reason else redaction.summary()

    span = TraceSpan(
        trace_id=trace.id,
        parent_span_id=span_request.parent_span_id,
        step_index=span_request.step_index,
        span_type=span_request.span_type,
        name=span_request.name,
        model_or_server=span_request.model_or_server,
        status=verdict.span_status,
        latency_ms=span_request.latency_ms,
        tokens_used=span_request.tokens_used,
        cost_usd=span_request.cost_usd,
        input_payload=safe_input,
        output_payload=safe_output,
        guardrail_reason=reason,
        requester_id=operator.get("sub"),
    )
    db.add(span)
    _apply_trace_aggregates(
        trace,
        tokens_used=span_request.tokens_used,
        cost_usd=span_request.cost_usd,
        latency_ms=span_request.latency_ms,
    )

    if verdict.trace_status:
        trace.status = verdict.trace_status
    if trace.status != TraceStatus.RUNNING:
        trace.ended_at = datetime.now(timezone.utc)

    await _safe_commit(db)
    await db.refresh(span)

    await sse_manager.publish(
        {
            "type": "span_ingested",
            "trace_id": trace.id,
            "span_id": span.id,
            "trace_status": trace.status.value,
            "span_status": span.status.value,
            "blocked": verdict.blocked,
        }
    )

    return SpanIngestResponse(
        span_id=span.id,
        trace_id=trace.id,
        span_status=span.status,
        trace_status=trace.status,
        guardrail_reason=span.guardrail_reason,
        blocked=verdict.blocked,
    )


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

@router.post(
    "/simulator/trigger",
    response_model=SimulatorTriggerResponse,
    dependencies=[Depends(csrf_protect)],
)
async def trigger_simulator(
    sim_request: SimulatorTriggerRequest,
    operator: Annotated[dict[str, Any], Depends(require_operator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SimulatorTriggerResponse:
    """Generate a realistic synthetic trace and broadcast it over SSE."""
    simulator = TraceSimulator()
    trace, spans = simulator.generate_trace(
        agent_name=sim_request.agent_name,
        environment=sim_request.environment,
    )
    trace.org_id = _operator_org(operator)

    db.add(trace)
    for span in spans:
        db.add(span)
    await _safe_commit(db)

    for span in spans:
        await sse_manager.publish(
            {
                "type": "simulator_span",
                "trace_id": trace.id,
                "span_id": span.id,
                "trace_status": trace.status.value,
                "span_status": span.status.value,
                "span_name": span.name,
            }
        )
        await asyncio.sleep(0.1)

    return SimulatorTriggerResponse(
        trace_id=trace.id,
        agent_name=trace.agent_name,
        status=trace.status,
        spans_created=len(spans),
    )


# ---------------------------------------------------------------------------
# HITL Span Decision
# ---------------------------------------------------------------------------

@router.post(
    "/spans/{span_id}/decision",
    response_model=SpanDecisionResponse,
    dependencies=[Depends(csrf_protect)],
)
async def span_decision(
    span_id: str,
    decision: SpanDecisionRequest,
    operator: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SpanDecisionResponse:
    """Approve or reject a span awaiting human-in-the-loop review."""
    org_id = _operator_org(operator)
    result = await db.execute(
        select(TraceSpan, AgentTrace)
        .join(AgentTrace, TraceSpan.trace_id == AgentTrace.id)
        .where(TraceSpan.id == span_id, AgentTrace.org_id == org_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Span not found")

    span, trace = row
    if span.status != SpanStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Span is not pending approval (current: {span.status.value})",
        )

    operator_sub = operator.get("sub", "unknown-operator")
    if (
        span.requester_id
        and span.requester_id == operator_sub
        and not settings.ALLOW_SELF_APPROVAL
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Separation of duties violation - requester cannot approve "
                "their own HITL escalation"
            ),
        )

    if decision.action == "APPROVE":
        span.status = SpanStatus.OK
        span.guardrail_reason = f"Approved by {operator_sub}: {decision.reviewer_note}"
        await db.flush()

        pending = await db.execute(
            select(func.count(TraceSpan.id)).where(
                TraceSpan.trace_id == trace.id,
                TraceSpan.status == SpanStatus.PENDING_APPROVAL,
            )
        )
        if (pending.scalar() or 0) == 0 and trace.status == TraceStatus.PENDING_HITL:
            trace.status = TraceStatus.COMPLETED
            trace.ended_at = datetime.now(timezone.utc)
    else:
        span.status = SpanStatus.ERROR
        span.guardrail_reason = f"Rejected by {operator_sub}: {decision.reviewer_note}"
        trace.status = TraceStatus.BLOCKED
        trace.ended_at = datetime.now(timezone.utc)

    await _safe_commit(db)

    await sse_manager.publish(
        {
            "type": "span_decision",
            "span_id": span.id,
            "trace_id": trace.id,
            "action": decision.action,
            "trace_status": trace.status.value,
        }
    )

    return SpanDecisionResponse(
        span_id=span.id,
        action=decision.action,
        trace_id=trace.id,
        trace_status=trace.status,
    )


# ---------------------------------------------------------------------------
# HITL Pending Queue
# ---------------------------------------------------------------------------

@router.get("/hitl/pending", response_model=HitlPendingResponse)
async def list_hitl_pending(
    operator: Annotated[dict[str, Any], Depends(require_operator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HitlPendingResponse:
    """Return spans awaiting human approval, scoped to the caller's org."""
    org_id = _operator_org(operator)
    result = await db.execute(
        select(TraceSpan, AgentTrace)
        .join(AgentTrace, TraceSpan.trace_id == AgentTrace.id)
        .where(
            TraceSpan.status == SpanStatus.PENDING_APPROVAL,
            AgentTrace.org_id == org_id,
        )
        .order_by(TraceSpan.created_at)
    )

    items = [
        HitlPendingItem(
            span_id=span.id,
            trace_id=trace.id,
            agent_name=trace.agent_name,
            name=span.name,
            model_or_server=span.model_or_server,
            input_payload=span.input_payload,
            guardrail_reason=span.guardrail_reason,
            created_at=span.created_at,
        )
        for span, trace in result.all()
    ]

    return HitlPendingResponse(items=items)


# ---------------------------------------------------------------------------
# Proxy Intercept (real-time agent interception)
# ---------------------------------------------------------------------------

@router.post("/proxy/intercept", response_model=ProxyInterceptResponse)
async def proxy_intercept(
    proxy_request: ProxyInterceptRequest,
    x_aegis_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> ProxyInterceptResponse:
    """Intercept a real agent tool call or LLM span and return the verdict.

    API-key only by design (machine-to-machine, no cookies, CSRF-exempt).
    """
    operator = await _api_key_principal(db, x_aegis_api_key, authorization)
    if not operator:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    org_id = _operator_org(operator)

    trace: AgentTrace | None = None
    if proxy_request.trace_id:
        result = await db.execute(
            select(AgentTrace).where(
                AgentTrace.id == proxy_request.trace_id,
                AgentTrace.org_id == org_id,
            )
        )
        trace = result.scalar_one_or_none()

        if trace is None:
            existing = await db.execute(
                select(AgentTrace.id).where(AgentTrace.id == proxy_request.trace_id)
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(status_code=404, detail="Trace not found")

    if trace is not None and trace.status == TraceStatus.LOOP_KILLED:
        return ProxyInterceptResponse(
            allowed=False,
            status="LOOP_KILLED",
            trace_id=trace.id,
            span_id="",
            reason="Trace was terminated by the loop guard",
        )

    if trace is None:
        trace = AgentTrace(
            id=proxy_request.trace_id or f"trc_{uuid.uuid4().hex[:8]}",
            agent_name=proxy_request.agent_name,
            environment=proxy_request.environment,
            org_id=org_id,
            status=TraceStatus.RUNNING,
            total_tokens=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_cost_usd=0.0,
            total_latency_ms=0,
            step_count=0,
        )
        db.add(trace)
        await db.flush()

    server_result = await db.execute(
        select(MCPServer).where(MCPServer.name == proxy_request.model_or_server)
    )
    server = server_result.scalar_one_or_none()

    span_request = SpanIngestRequest(
        trace_id=trace.id,
        agent_name=proxy_request.agent_name,
        environment=proxy_request.environment,
        span_type=proxy_request.span_type,
        name=proxy_request.name,
        model_or_server=proxy_request.model_or_server,
        parent_span_id=proxy_request.parent_span_id,
        step_index=proxy_request.step_index,
        latency_ms=proxy_request.latency_ms,
        tokens_used=proxy_request.tokens_used,
        cost_usd=proxy_request.cost_usd,
        input_payload=proxy_request.input_payload,
        output_payload=proxy_request.output_payload,
    )
    verdict = await _evaluate_guardrail(span_request, trace, server)

    if verdict.span_status == SpanStatus.BLOCKED:
        response_status = (
            "LOOP_KILLED" if verdict.trace_status == TraceStatus.LOOP_KILLED else "BLOCKED"
        )
        allowed = False
    elif verdict.span_status == SpanStatus.PENDING_APPROVAL:
        response_status = "PENDING_APPROVAL"
        allowed = True
    else:
        response_status = "OK"
        allowed = True

    safe_input, redaction = redact_mapping(proxy_request.input_payload)
    safe_output, output_redaction = redact_mapping(proxy_request.output_payload)
    redaction.extend(output_redaction)
    reason = verdict.reason
    if redaction.summary():
        reason = f"{reason} | {redaction.summary()}" if reason else redaction.summary()

    span = TraceSpan(
        trace_id=trace.id,
        parent_span_id=proxy_request.parent_span_id,
        step_index=proxy_request.step_index,
        span_type=proxy_request.span_type,
        name=proxy_request.name,
        model_or_server=proxy_request.model_or_server,
        status=verdict.span_status,
        latency_ms=proxy_request.latency_ms,
        tokens_used=proxy_request.tokens_used,
        cost_usd=proxy_request.cost_usd,
        input_payload=safe_input,
        output_payload=safe_output,
        guardrail_reason=reason,
        requester_id=operator.get("sub"),
    )
    db.add(span)
    _apply_trace_aggregates(
        trace,
        tokens_used=proxy_request.tokens_used,
        cost_usd=proxy_request.cost_usd,
        latency_ms=proxy_request.latency_ms,
    )

    if verdict.trace_status:
        trace.status = verdict.trace_status
    if trace.status != TraceStatus.RUNNING:
        trace.ended_at = datetime.now(timezone.utc)

    await _safe_commit(db)
    await db.refresh(span)

    await sse_manager.publish(
        {
            "type": "span_ingested",
            "trace_id": trace.id,
            "span_id": span.id,
            "trace_status": trace.status.value,
            "span_status": span.status.value,
            "blocked": verdict.blocked,
        }
    )

    return ProxyInterceptResponse(
        allowed=allowed,
        status=response_status,
        trace_id=trace.id,
        span_id=span.id,
        reason=verdict.reason,
    )


# ---------------------------------------------------------------------------
# Span status polling (SDK HITL long-polling)
# ---------------------------------------------------------------------------

@router.get("/spans/{span_id}/status", response_model=SpanStatusResponse)
async def get_span_status(
    span_id: str,
    x_aegis_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> SpanStatusResponse:
    """Poll a span's status. API-key only; used by the SDK during HITL."""
    operator = await _api_key_principal(db, x_aegis_api_key, authorization)
    if not operator:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    result = await db.execute(
        select(TraceSpan, AgentTrace)
        .join(AgentTrace, TraceSpan.trace_id == AgentTrace.id)
        .where(
            TraceSpan.id == span_id,
            AgentTrace.org_id == _operator_org(operator),
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Span not found")

    span, trace = row
    return SpanStatusResponse(
        span_id=span.id,
        trace_id=trace.id,
        status=span.status,
        trace_status=trace.status,
        guardrail_reason=span.guardrail_reason,
    )


# ---------------------------------------------------------------------------
# API Key management
# ---------------------------------------------------------------------------

@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    operator: Annotated[dict[str, Any], Depends(require_operator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[APIKeyResponse]:
    """List the caller's API keys (never the raw key or hash)."""
    result = await db.execute(
        select(APIKey)
        .where(APIKey.org_id == _operator_org(operator))
        .order_by(APIKey.created_at.desc())
    )
    return [APIKeyResponse.model_validate(key) for key in result.scalars().all()]


@router.post("/api-keys", response_model=APIKeyCreateResponse, dependencies=[Depends(csrf_protect)])
async def create_api_key(
    key_request: APIKeyCreate,
    operator: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyCreateResponse:
    """Create a new API key. The raw key is returned only once."""
    raw_key, prefix, key_hash = generate_api_key()

    api_key = APIKey(
        name=key_request.name,
        org_id=_operator_org(operator),
        key_prefix=prefix,
        key_hash=key_hash,
        is_active=True,
    )
    db.add(api_key)
    await _safe_commit(db)
    await db.refresh(api_key)

    return APIKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        raw_key=raw_key,
        created_at=api_key.created_at,
    )


@router.delete("/api-keys/{key_id}", dependencies=[Depends(csrf_protect)])
async def revoke_api_key(
    key_id: str,
    operator: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Revoke (soft delete) one of the caller's API keys."""
    result = await db.execute(
        select(APIKey).where(
            APIKey.id == key_id,
            APIKey.org_id == _operator_org(operator),
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.is_active = False
    await _safe_commit(db)

    return {"status": "revoked", "key_id": key_id}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/analytics/summary", response_model=AnalyticsSummary)
async def analytics_summary(
    operator: Annotated[dict[str, Any], Depends(require_operator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AnalyticsSummary:
    """Aggregate FinOps metrics for the caller's organization."""
    org_id = _operator_org(operator)
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    spend = await db.execute(
        select(func.sum(AgentTrace.total_cost_usd)).where(
            AgentTrace.started_at >= day_ago,
            AgentTrace.org_id == org_id,
        )
    )
    total_spend = float(spend.scalar() or 0.0)

    active = await db.execute(
        select(func.count(AgentTrace.id)).where(
            AgentTrace.status == TraceStatus.RUNNING,
            AgentTrace.org_id == org_id,
        )
    )
    active_sessions = int(active.scalar() or 0)

    interceptions = await db.execute(
        select(func.count(TraceSpan.id))
        .join(AgentTrace, TraceSpan.trace_id == AgentTrace.id)
        .where(
            TraceSpan.status == SpanStatus.BLOCKED,
            AgentTrace.org_id == org_id,
        )
    )
    guardrail_interceptions = int(interceptions.scalar() or 0)

    ttft = await db.execute(
        select(func.avg(TraceSpan.latency_ms))
        .join(AgentTrace, TraceSpan.trace_id == AgentTrace.id)
        .where(
            TraceSpan.step_index == 0,
            AgentTrace.org_id == org_id,
        )
    )
    mean_ttft = float(ttft.scalar() or 0.0)

    breakdown = await db.execute(
        select(TraceSpan.model_or_server, func.sum(TraceSpan.cost_usd))
        .join(AgentTrace, TraceSpan.trace_id == AgentTrace.id)
        .where(AgentTrace.org_id == org_id)
        .group_by(TraceSpan.model_or_server)
    )
    model_cost_breakdown = {
        (str(row[0]) if row[0] is not None else "unknown"): round(float(row[1] or 0.0), 4)
        for row in breakdown.all()
    }

    hourly_series: list[dict[str, Any]] = []
    for i in range(24):
        hour_start = now - timedelta(hours=i + 1)
        hour_end = now - timedelta(hours=i)
        bucket = await db.execute(
            select(func.sum(AgentTrace.total_tokens)).where(
                AgentTrace.started_at >= hour_start,
                AgentTrace.started_at < hour_end,
                AgentTrace.org_id == org_id,
            )
        )
        hourly_series.append(
            {"hour": hour_start.isoformat(), "tokens": int(bucket.scalar() or 0)}
        )

    return AnalyticsSummary(
        total_spend_24h_usd=round(total_spend, 4),
        active_sessions=active_sessions,
        guardrail_interceptions=guardrail_interceptions,
        mean_ttft_ms=round(mean_ttft, 2),
        model_cost_breakdown=model_cost_breakdown,
        hourly_token_series=hourly_series,
    )


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

_SSE_FRAME_END = chr(10) * 2
_SSE_HEARTBEAT_SECONDS = 15.0


@router.get("/stream/events")
async def stream_events(
    operator: Annotated[dict[str, Any], Depends(require_operator)],
) -> StreamingResponse:
    """Stream live trace events (SSE) with keep-alive heartbeats.

    Disconnects are handled by Starlette cancelling the generator, whose
    ``finally`` unregisters the subscriber. We deliberately avoid awaiting
    ``request.is_disconnected()`` before the first yield: under
    ``BaseHTTPMiddleware`` that await blocks until a client message arrives
    and stalls the stream.
    """
    async def event_generator():
        queue = await sse_manager.subscribe()
        try:
            yield "retry: 5000" + _SSE_FRAME_END
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=_SSE_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    event = {"type": "heartbeat"}
                yield "data: " + json.dumps(event) + _SSE_FRAME_END
        except asyncio.CancelledError:
            raise
        finally:
            await sse_manager.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Span completion (pre-flight SDK enforcement)
# ---------------------------------------------------------------------------

@router.post("/spans/{span_id}/complete", response_model=SpanCompleteResponse)
async def complete_span(
    span_id: str,
    completion: SpanCompleteRequest,
    x_aegis_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> SpanCompleteResponse:
    """Attach post-execution output/usage to a span created before execution.

    The SDK authorises a tool call first (creating the span in an ``OK`` or
    ``PENDING_APPROVAL`` state), runs it, then reports the result here. Blocked
    or rejected spans are never completed because the call never ran.
    API-key only, like the intercept endpoint.
    """
    operator = await _api_key_principal(db, x_aegis_api_key, authorization)
    if not operator:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    result = await db.execute(
        select(TraceSpan, AgentTrace)
        .join(AgentTrace, TraceSpan.trace_id == AgentTrace.id)
        .where(
            TraceSpan.id == span_id,
            AgentTrace.org_id == _operator_org(operator),
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Span not found")

    span, trace = row
    if span.status == SpanStatus.BLOCKED:
        raise HTTPException(status_code=409, detail="Span was blocked and cannot be completed")
    if span.status == SpanStatus.ERROR:
        raise HTTPException(status_code=409, detail="Span was rejected and cannot be completed")

    # Aggregate only the delta: pre-flight spans may already carry estimates.
    delta_tokens = max(0, completion.tokens_used - (span.tokens_used or 0))
    delta_cost = max(0.0, completion.cost_usd - (span.cost_usd or 0.0))
    delta_latency = max(0, completion.latency_ms - (span.latency_ms or 0))

    safe_output, _ = redact_mapping(completion.output_payload)
    span.output_payload = safe_output
    span.latency_ms = completion.latency_ms
    span.tokens_used = completion.tokens_used
    span.cost_usd = completion.cost_usd

    trace.total_tokens = (trace.total_tokens or 0) + delta_tokens
    trace.prompt_tokens = (trace.prompt_tokens or 0) + (delta_tokens // 2)
    trace.completion_tokens = (trace.completion_tokens or 0) + (
        delta_tokens - (delta_tokens // 2)
    )
    trace.total_cost_usd = round((trace.total_cost_usd or 0.0) + delta_cost, 6)
    trace.total_latency_ms = (trace.total_latency_ms or 0) + delta_latency

    await _safe_commit(db)

    await sse_manager.publish(
        {
            "type": "span_completed",
            "trace_id": trace.id,
            "span_id": span.id,
            "trace_status": trace.status.value,
            "span_status": span.status.value,
        }
    )

    return SpanCompleteResponse(
        span_id=span.id,
        trace_id=trace.id,
        span_status=span.status,
        trace_status=trace.status,
    )


# ---------------------------------------------------------------------------
# MCP protocol gateway (JSON-RPC 2.0)
# ---------------------------------------------------------------------------

@router.post("/mcp-servers/{server_id}/tools/reset", response_model=MCPServerResponse,
             dependencies=[Depends(csrf_protect)])
async def reset_server_tool_manifest(
    server_id: str,
    operator: Annotated[dict[str, Any], Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MCPServer:
    """Clear the pinned tool manifest so the next tools/list re-pins it.

    This is the explicit admin action required after a legitimate upstream
    catalog change; until it runs, rug-pull protection rejects the new manifest.
    """
    result = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    server.tool_manifest_hash = None
    server.pinned_tools = None
    await _safe_commit(db)
    await db.refresh(server)
    logger.info("Tool manifest reset for %s by %s", server.name, operator.get("sub"))
    return server


@router.post("/mcp/{server_name}/rpc")
async def mcp_jsonrpc(
    server_name: str,
    payload: dict[str, Any] = Body(...),
    x_aegis_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Any:
    """Proxy one MCP JSON-RPC 2.0 message through the guardrail gateway.

    API-key only (machine-to-machine). Notifications return ``202 Accepted``
    with no body; every other message returns a JSON-RPC response envelope.
    """
    operator = await _api_key_principal(db, x_aegis_api_key, authorization)
    if not operator:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    result = await db.execute(select(MCPServer).where(MCPServer.name == server_name))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

    try:
        response = await handle_mcp_rpc(
            server=server, payload=payload, db=db, operator=operator
        )
    except TenantMismatch as exc:
        raise HTTPException(status_code=404, detail="Trace not found") from exc

    if response is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return JSONResponse(response)


# ---------------------------------------------------------------------------
# OpenTelemetry OTLP/HTTP JSON trace receiver
# ---------------------------------------------------------------------------

@router.post("/otlp/v1/traces")
async def otlp_traces(
    payload: dict[str, Any] = Body(...),
    x_aegis_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> Any:
    """Ingest OTLP/HTTP JSON spans and map ``gen_ai.*`` attributes.

    Authenticated with ``X-Aegis-API-Key`` or ``Authorization: Bearer <key>``,
    matching the OTel exporter's ``headers`` configuration.
    """
    operator = await _api_key_principal(db, x_aegis_api_key, authorization)
    if not operator:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    try:
        return await ingest_otlp(payload, db, operator)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
