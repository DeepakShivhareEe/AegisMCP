"""Rich initial seed data: 4 MCP servers and 6 realistic traces."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import AgentTrace, APIKey, MCPServer, TraceSpan
from app.schemas import (
    PermissionMode,
    ServerStatus,
    SpanStatus,
    SpanType,
    TraceStatus,
    TransportType,
)


_logger = logging.getLogger(__name__)


async def seed_database() -> None:
    """Seed demo data, development only.

    Production databases must start empty and only ever hold data produced by
    real traffic, so this returns immediately unless ``ENVIRONMENT`` is
    literally ``development`` *and* every table is empty.
    """
    if settings.ENVIRONMENT.strip().lower() != "development":
        _logger.info(
            "Seed skipped: ENVIRONMENT=%s (production databases start empty)",
            settings.ENVIRONMENT,
        )
        return

    async with AsyncSessionLocal() as session:
        for model in (MCPServer, AgentTrace, TraceSpan, APIKey):
            existing = await session.execute(select(model).limit(1))
            if existing.scalars().first() is not None:
                _logger.info(
                    "Seed skipped: %s already has rows", model.__tablename__
                )
                return

        now = datetime.now(timezone.utc)

        servers = [
            MCPServer(
                id="mcp-postgres-prod",
                name="postgres-prod-mcp",
                endpoint_url="http://postgres-mcp.internal:8080",
                transport=TransportType.SSE,
                status=ServerStatus.ONLINE,
                permission_mode=PermissionMode.HITL_REQUIRED,
                max_cost_usd_per_run=0.50,
                max_steps_per_run=12,
                blocked_patterns=["DROP TABLE", "DELETE FROM", "TRUNCATE", "rm -rf"],
                created_at=now - timedelta(days=7),
            ),
            MCPServer(
                id="mcp-github-repo",
                name="github-repo-mcp",
                endpoint_url="http://github-mcp.internal:8081",
                transport=TransportType.STDIO,
                status=ServerStatus.ONLINE,
                permission_mode=PermissionMode.READ_ONLY,
                max_cost_usd_per_run=0.25,
                max_steps_per_run=10,
                blocked_patterns=["sk_live_", "ghp_", "DELETE", "rm -rf"],
                created_at=now - timedelta(days=6),
            ),
            MCPServer(
                id="mcp-filesystem-sandbox",
                name="filesystem-sandbox-mcp",
                endpoint_url="http://fs-mcp.internal:8082",
                transport=TransportType.STDIO,
                status=ServerStatus.ONLINE,
                permission_mode=PermissionMode.ALLOW_ALL,
                max_cost_usd_per_run=0.10,
                max_steps_per_run=8,
                blocked_patterns=["rm -rf", "/etc/", "/root/", "sudo "],
                created_at=now - timedelta(days=5),
            ),
            MCPServer(
                id="mcp-stripe-billing",
                name="stripe-billing-mcp",
                endpoint_url="http://stripe-mcp.internal:8083",
                transport=TransportType.WEBSOCKET,
                status=ServerStatus.DEGRADED,
                permission_mode=PermissionMode.HITL_REQUIRED,
                max_cost_usd_per_run=1.00,
                max_steps_per_run=15,
                blocked_patterns=["sk_live_", "refund.*all", "DELETE.*customer"],
                created_at=now - timedelta(days=4),
            ),
        ]
        for srv in servers:
            session.add(srv)
        await session.flush()

        # Seed a default API key. Only the SHA-256 hash is persisted; the raw
        # key never touches disk unless the operator supplied SEED_API_KEY.
        from app.security import generate_api_key, hash_api_key, split_api_key

        raw_key = settings.SEED_API_KEY
        prefix, raw_part = split_api_key(raw_key) if raw_key else (None, "")
        if not prefix:
            raw_key, prefix, _ = generate_api_key()
            _, raw_part = split_api_key(raw_key)

        default_key = APIKey(
            id="api-key-default-dev",
            name="Default Development Key",
            org_id=settings.DEFAULT_ORG_ID,
            key_prefix=prefix,
            key_hash=hash_api_key(raw_part),
            is_active=True,
            created_at=now - timedelta(days=1),
        )
        session.add(default_key)
        await session.flush()
        _logger.info("Seeded development API key with prefix %s", prefix)

        traces = [
            AgentTrace(
                id="trc_9f8a7d6c",
                agent_name="sql-analyst-v2",
                environment="production",
                status=TraceStatus.COMPLETED,
                total_tokens=3000,
                prompt_tokens=1500,
                completion_tokens=1500,
                total_cost_usd=0.057,
                total_latency_ms=830,
                step_count=4,
                started_at=now - timedelta(hours=3),
                ended_at=now - timedelta(hours=2, minutes=59),
                mcp_server_id="mcp-postgres-prod",
            ),
            AgentTrace(
                id="trc_b2c4d8e1",
                agent_name="customer-refund-agent",
                environment="production",
                status=TraceStatus.BLOCKED,
                total_tokens=1600,
                prompt_tokens=800,
                completion_tokens=800,
                total_cost_usd=0.036,
                total_latency_ms=690,
                step_count=3,
                started_at=now - timedelta(hours=2),
                ended_at=now - timedelta(hours=2),
                mcp_server_id="mcp-stripe-billing",
            ),
            AgentTrace(
                id="trc_loop_3a7f9c",
                agent_name="autonomous-code-reviewer",
                environment="staging",
                status=TraceStatus.LOOP_KILLED,
                total_tokens=8500,
                prompt_tokens=4200,
                completion_tokens=4300,
                total_cost_usd=0.168,
                total_latency_ms=2100,
                step_count=15,
                started_at=now - timedelta(hours=1, minutes=45),
                ended_at=now - timedelta(hours=1, minutes=42),
                mcp_server_id="mcp-github-repo",
            ),
            AgentTrace(
                id="trc_hitl_5k2m8p",
                agent_name="pr-sec-auditor",
                environment="production",
                status=TraceStatus.PENDING_HITL,
                total_tokens=2400,
                prompt_tokens=1200,
                completion_tokens=1200,
                total_cost_usd=0.044,
                total_latency_ms=750,
                step_count=5,
                started_at=now - timedelta(minutes=30),
                ended_at=None,
                mcp_server_id="mcp-github-repo",
            ),
            AgentTrace(
                id="trc_rag_7n3x9q",
                agent_name="rag-researcher-v1",
                environment="staging",
                status=TraceStatus.COMPLETED,
                total_tokens=1800,
                prompt_tokens=900,
                completion_tokens=900,
                total_cost_usd=0.026,
                total_latency_ms=540,
                step_count=3,
                started_at=now - timedelta(hours=5),
                ended_at=now - timedelta(hours=4, minutes=55),
                mcp_server_id="mcp-filesystem-sandbox",
            ),
            AgentTrace(
                id="trc_run_4t7v2w",
                agent_name="sql-analyst-v2",
                environment="production",
                status=TraceStatus.RUNNING,
                total_tokens=2100,
                prompt_tokens=1050,
                completion_tokens=1050,
                total_cost_usd=0.042,
                total_latency_ms=610,
                step_count=3,
                started_at=now - timedelta(minutes=10),
                ended_at=None,
                mcp_server_id="mcp-postgres-prod",
            ),
        ]
        for t in traces:
            session.add(t)
        await session.flush()

        t1_spans = [
            TraceSpan(id="spn_1a2b3c4d", trace_id="trc_9f8a7d6c", parent_span_id=None, step_index=0,
                      span_type=SpanType.LLM_INFERENCE, name="claude-3-7-sonnet", model_or_server="claude-3-7-sonnet",
                      status=SpanStatus.OK, latency_ms=240, tokens_used=1200, cost_usd=0.024,
                      input_payload={"query": "Analyze Q4 sales"}, output_payload={"insights": "Revenue up 12%"}),
            TraceSpan(id="spn_2b3c4d5e", trace_id="trc_9f8a7d6c", parent_span_id="spn_1a2b3c4d", step_index=1,
                      span_type=SpanType.MCP_TOOL_CALL, name="mcp:postgres:execute_query", model_or_server="postgres-prod-mcp",
                      status=SpanStatus.OK, latency_ms=180, tokens_used=0, cost_usd=0.0,
                      input_payload={"sql": "SELECT * FROM sales WHERE quarter = 'Q4'"}, output_payload={"rows": 1500}),
            TraceSpan(id="spn_3c4d5e6f", trace_id="trc_9f8a7d6c", parent_span_id="spn_2b3c4d5e", step_index=2,
                      span_type=SpanType.RAG_RETRIEVAL, name="vector-store-sales", model_or_server="vector-store",
                      status=SpanStatus.OK, latency_ms=90, tokens_used=300, cost_usd=0.003,
                      input_payload={"doc": "sales_schema"}, output_payload={"matches": 5}),
            TraceSpan(id="spn_4d5e6f7g", trace_id="trc_9f8a7d6c", parent_span_id="spn_3c4d5e6f", step_index=3,
                      span_type=SpanType.LLM_INFERENCE, name="claude-3-7-sonnet", model_or_server="claude-3-7-sonnet",
                      status=SpanStatus.OK, latency_ms=320, tokens_used=1500, cost_usd=0.030,
                      input_payload={"context": "sales_data"}, output_payload={"report": "Q4 summary"}),
        ]

        t2_spans = [
            TraceSpan(id="spn_5e6f7g8h", trace_id="trc_b2c4d8e1", parent_span_id=None, step_index=0,
                      span_type=SpanType.LLM_INFERENCE, name="gemini-2.5-pro", model_or_server="gemini-2.5-pro",
                      status=SpanStatus.OK, latency_ms=180, tokens_used=900, cost_usd=0.018),
            TraceSpan(id="spn_6f7g8h9i", trace_id="trc_b2c4d8e1", parent_span_id="spn_5e6f7g8h", step_index=1,
                      span_type=SpanType.MCP_TOOL_CALL, name="mcp:stripe:refund_payment", model_or_server="stripe-billing-mcp",
                      status=SpanStatus.BLOCKED, latency_ms=250, tokens_used=0, cost_usd=0.0,
                      input_payload={"charge": "ch_3XyZ", "action": "refund_all"}, output_payload=None,
                      guardrail_reason="Blocked pattern matched: 'refund.*all'"),
            TraceSpan(id="spn_7g8h9i0j", trace_id="trc_b2c4d8e1", parent_span_id="spn_6f7g8h9i", step_index=2,
                      span_type=SpanType.LLM_INFERENCE, name="gemini-2.5-pro", model_or_server="gemini-2.5-pro",
                      status=SpanStatus.ERROR, latency_ms=160, tokens_used=700, cost_usd=0.014,
                      input_payload={"error": "guardrail_blocked"}, output_payload=None),
        ]

        t3_spans = [
            TraceSpan(id="spn_8h9i0j1k", trace_id="trc_loop_3a7f9c", parent_span_id=None, step_index=0,
                      span_type=SpanType.LLM_INFERENCE, name="llama-3.3-70b", model_or_server="llama-3.3-70b",
                      status=SpanStatus.OK, latency_ms=400, tokens_used=2000, cost_usd=0.040),
            TraceSpan(id="spn_9i0j1k2l", trace_id="trc_loop_3a7f9c", parent_span_id="spn_8h9i0j1k", step_index=1,
                      span_type=SpanType.MCP_TOOL_CALL, name="mcp:github:list_files", model_or_server="github-repo-mcp",
                      status=SpanStatus.OK, latency_ms=140, tokens_used=0, cost_usd=0.0),
            TraceSpan(id="spn_0j1k2l3m", trace_id="trc_loop_3a7f9c", parent_span_id="spn_9i0j1k2l", step_index=2,
                      span_type=SpanType.RAG_RETRIEVAL, name="security-rules", model_or_server="vector-store",
                      status=SpanStatus.OK, latency_ms=180, tokens_used=500, cost_usd=0.005),
            TraceSpan(id="spn_1k2l3m4n", trace_id="trc_loop_3a7f9c", parent_span_id="spn_0j1k2l3m", step_index=3,
                      span_type=SpanType.LLM_INFERENCE, name="llama-3.3-70b", model_or_server="llama-3.3-70b",
                      status=SpanStatus.OK, latency_ms=450, tokens_used=2200, cost_usd=0.044),
            TraceSpan(id="spn_2l3m4n5o", trace_id="trc_loop_3a7f9c", parent_span_id="spn_1k2l3m4n", step_index=4,
                      span_type=SpanType.MCP_TOOL_CALL, name="mcp:github:create_review", model_or_server="github-repo-mcp",
                      status=SpanStatus.BLOCKED, latency_ms=190, tokens_used=0, cost_usd=0.0,
                      guardrail_reason="Step limit exceeded: step 15 > max 12 per run"),
        ]

        t4_spans = [
            TraceSpan(id="spn_3m4n5o6p", trace_id="trc_hitl_5k2m8p", parent_span_id=None, step_index=0,
                      span_type=SpanType.LLM_INFERENCE, name="gpt-4o", model_or_server="gpt-4o",
                      status=SpanStatus.OK, latency_ms=150, tokens_used=800, cost_usd=0.016),
            TraceSpan(id="spn_4n5o6p7q", trace_id="trc_hitl_5k2m8p", parent_span_id="spn_3m4n5o6p", step_index=1,
                      span_type=SpanType.MCP_TOOL_CALL, name="mcp:github:list_files", model_or_server="github-repo-mcp",
                      status=SpanStatus.OK, latency_ms=120, tokens_used=0, cost_usd=0.0),
            TraceSpan(id="spn_5o6p7q8r", trace_id="trc_hitl_5k2m8p", parent_span_id="spn_4n5o6p7q", step_index=2,
                      span_type=SpanType.RAG_RETRIEVAL, name="codebase-index", model_or_server="vector-store",
                      status=SpanStatus.OK, latency_ms=200, tokens_used=600, cost_usd=0.006),
            TraceSpan(id="spn_6p7q8r9s", trace_id="trc_hitl_5k2m8p", parent_span_id="spn_5o6p7q8r", step_index=3,
                      span_type=SpanType.LLM_INFERENCE, name="gpt-4o", model_or_server="gpt-4o",
                      status=SpanStatus.OK, latency_ms=280, tokens_used=1100, cost_usd=0.022),
            TraceSpan(id="spn_7q8r9s0t", trace_id="trc_hitl_5k2m8p", parent_span_id="spn_6p7q8r9s", step_index=4,
                      span_type=SpanType.MCP_TOOL_CALL, name="mcp:github:create_issue", model_or_server="github-repo-mcp",
                      status=SpanStatus.PENDING_APPROVAL, latency_ms=200, tokens_used=0, cost_usd=0.0,
                      guardrail_reason="HITL approval required for MCP tool call"),
        ]

        t5_spans = [
            TraceSpan(id="spn_8r9s0t1u", trace_id="trc_rag_7n3x9q", parent_span_id=None, step_index=0,
                      span_type=SpanType.RAG_RETRIEVAL, name="vector-store-sales", model_or_server="vector-store",
                      status=SpanStatus.OK, latency_ms=100, tokens_used=400, cost_usd=0.004),
            TraceSpan(id="spn_9s0t1u2v", trace_id="trc_rag_7n3x9q", parent_span_id="spn_8r9s0t1u", step_index=1,
                      span_type=SpanType.LLM_INFERENCE, name="gemini-2.5-pro", model_or_server="gemini-2.5-pro",
                      status=SpanStatus.OK, latency_ms=160, tokens_used=900, cost_usd=0.018),
            TraceSpan(id="spn_0t1u2v3w", trace_id="trc_rag_7n3x9q", parent_span_id="spn_9s0t1u2v", step_index=2,
                      span_type=SpanType.RAG_RETRIEVAL, name="policy-docs", model_or_server="vector-store",
                      status=SpanStatus.OK, latency_ms=120, tokens_used=500, cost_usd=0.004),
        ]

        t6_spans = [
            TraceSpan(id="spn_1u2v3w4x", trace_id="trc_run_4t7v2w", parent_span_id=None, step_index=0,
                      span_type=SpanType.LLM_INFERENCE, name="claude-3-7-sonnet", model_or_server="claude-3-7-sonnet",
                      status=SpanStatus.OK, latency_ms=200, tokens_used=1000, cost_usd=0.020),
            TraceSpan(id="spn_2v3w4x5y", trace_id="trc_run_4t7v2w", parent_span_id="spn_1u2v3w4x", step_index=1,
                      span_type=SpanType.MCP_TOOL_CALL, name="mcp:postgres:execute_query", model_or_server="postgres-prod-mcp",
                      status=SpanStatus.OK, latency_ms=150, tokens_used=0, cost_usd=0.0),
            TraceSpan(id="spn_3w4x5y6z", trace_id="trc_run_4t7v2w", parent_span_id="spn_2v3w4x5y", step_index=2,
                      span_type=SpanType.RAG_RETRIEVAL, name="vector-store-sales", model_or_server="vector-store",
                      status=SpanStatus.OK, latency_ms=80, tokens_used=300, cost_usd=0.003),
        ]

        all_spans = t1_spans + t2_spans + t3_spans + t4_spans + t5_spans + t6_spans
        for span in all_spans:
            session.add(span)

        await session.commit()