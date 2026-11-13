"""Multi-step realistic agent trace generator for the live traffic simulator."""

import random
import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar

from app.enums import SpanStatus, SpanType, TraceStatus
from app.models import AgentTrace, TraceSpan


class TraceSimulator:
    """Generates realistic 4-7 step multi-agent workflows."""

    SCENARIOS: ClassVar[list[dict[str, Any]]] = [
        {
            "agent_name": "sql-analyst-v2",
            "steps": [
                ("LLM_INFERENCE", "claude-3-7-sonnet", "Analyze quarterly sales data", 240, 1200, 0.024),
                ("MCP_TOOL_CALL", "mcp:postgres:execute_query", "SELECT * FROM sales WHERE quarter = 'Q4'", 180, 0, 0.0),
                ("RAG_RETRIEVAL", "vector-store-sales", "Retrieve sales schema documentation", 90, 300, 0.003),
                ("LLM_INFERENCE", "claude-3-7-sonnet", "Generate sales insights report", 320, 1500, 0.030),
            ],
        },
        {
            "agent_name": "pr-sec-auditor",
            "steps": [
                ("LLM_INFERENCE", "gpt-4o", "Review pull request #4821", 150, 800, 0.016),
                ("MCP_TOOL_CALL", "mcp:github:list_files", "List changed files in PR", 120, 0, 0.0),
                ("RAG_RETRIEVAL", "codebase-index", "Find similar security patterns", 200, 600, 0.006),
                ("LLM_INFERENCE", "gpt-4o", "Generate security audit findings", 280, 1100, 0.022),
                ("MCP_TOOL_CALL", "mcp:github:create_issue", "File security ticket", 200, 0, 0.0),
            ],
        },
        {
            "agent_name": "customer-refund-agent",
            "steps": [
                ("LLM_INFERENCE", "gemini-2.5-pro", "Process refund request REF-7731", 180, 900, 0.018),
                ("MCP_TOOL_CALL", "mcp:stripe:refund_payment", "Issue refund for charge ch_3XyZ", 250, 0, 0.0),
                ("RAG_RETRIEVAL", "policy-docs", "Retrieve refund policy guidelines", 100, 400, 0.004),
                ("LLM_INFERENCE", "gemini-2.5-pro", "Confirm refund completion", 160, 700, 0.014),
            ],
        },
        {
            "agent_name": "autonomous-code-reviewer",
            "steps": [
                ("LLM_INFERENCE", "llama-3.3-70b", "Review authentication module", 400, 2000, 0.040),
                ("MCP_TOOL_CALL", "mcp:github:list_files", "List modified source files", 140, 0, 0.0),
                ("RAG_RETRIEVAL", "security-rules", "Retrieve OWASP top 10 rules", 180, 500, 0.005),
                ("LLM_INFERENCE", "llama-3.3-70b", "Generate review comments", 450, 2200, 0.044),
                ("MCP_TOOL_CALL", "mcp:github:create_review", "Submit PR review", 190, 0, 0.0),
            ],
        },
    ]

    def generate_trace(
        self,
        agent_name: str = "simulated-agent",
        environment: str = "production",
    ) -> tuple[AgentTrace, list[TraceSpan]]:
        scenario = self._pick_scenario(agent_name)
        trace_id = f"trc_{uuid.uuid4().hex[:8]}"

        trace = AgentTrace(
            id=trace_id,
            agent_name=scenario["agent_name"],
            environment=environment,
            status=TraceStatus.RUNNING,
            total_tokens=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_cost_usd=0.0,
            total_latency_ms=0,
            step_count=0,
        )

        spans: list[TraceSpan] = []
        for i, (span_type, model_server, name, latency, tokens, cost) in enumerate(scenario["steps"]):
            span = TraceSpan(
                id=f"spn_{uuid.uuid4().hex[:8]}",
                trace_id=trace_id,
                parent_span_id=spans[-1].id if spans else None,
                step_index=i,
                span_type=SpanType(span_type),
                name=name,
                model_or_server=model_server,
                status=SpanStatus.OK,
                latency_ms=latency,
                tokens_used=tokens,
                cost_usd=cost,
                input_payload={"agent": scenario["agent_name"], "step": i},
                output_payload={"result": "success"},
                guardrail_reason=None,
                created_at=datetime.now(timezone.utc),
            )
            spans.append(span)
            trace.total_tokens += tokens
            trace.total_cost_usd += cost
            trace.total_latency_ms += latency
            trace.step_count += 1

        # Pick a final status and keep span-level state consistent with it so
        # the dashboard never shows, for example, a BLOCKED trace whose spans
        # are all OK.
        statuses = [
            (TraceStatus.COMPLETED, 0.55),
            (TraceStatus.BLOCKED, 0.20),
            (TraceStatus.PENDING_HITL, 0.15),
            (TraceStatus.LOOP_KILLED, 0.10),
        ]
        roll = random.random()
        cumulative = 0.0
        trace.status = statuses[-1][0]
        for candidate, probability in statuses:
            cumulative += probability
            if roll <= cumulative:
                trace.status = candidate
                break

        if spans:
            last_span = spans[-1]
            if trace.status == TraceStatus.BLOCKED:
                sample = random.choice(["DROP TABLE", "sk_live_", "rm -rf"])
                last_span.status = SpanStatus.BLOCKED
                last_span.guardrail_reason = f"Blocked pattern matched: '{sample}'"
            elif trace.status == TraceStatus.LOOP_KILLED:
                last_span.status = SpanStatus.BLOCKED
                last_span.guardrail_reason = (
                    "Step limit exceeded: loop guard terminated the run"
                )
            elif trace.status == TraceStatus.PENDING_HITL:
                last_span.status = SpanStatus.PENDING_APPROVAL
                last_span.guardrail_reason = "HITL approval required for MCP tool call"

        trace.ended_at = (
            None if trace.status == TraceStatus.PENDING_HITL else datetime.now(timezone.utc)
        )
        trace.total_cost_usd = round(trace.total_cost_usd, 6)
        return trace, spans

    def _pick_scenario(self, agent_name: str) -> dict[str, Any]:
        for scenario in self.SCENARIOS:
            if scenario["agent_name"] == agent_name:
                return scenario
        return self.SCENARIOS[0]