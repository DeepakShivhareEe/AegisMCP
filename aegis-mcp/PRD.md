# Product Requirements Document (PRD): AegisMCP


# Product Requirements Document (PRD): AegisMCP

## 1. Executive Summary
**Product Name:** AegisMCP
**Category:** AI Agent Observability, FinOps Metering & MCP Runtime Security Gateway
**Core Value Proposition:** A unified control plane and proxy gateway that monitors multi-step AI agent workflows in real time, visualizes execution graphs (LLM calls, RAG retrievals, MCP tool executions), enforces granular security guardrails on tool calls, and prevents runaway token burn via automated circuit breakers.

## 2. Target Personas
1. **AI/ML Systems Engineer:** Needs sub-millisecond trace visibility into multi-agent trajectories, prompt/completion payloads, latency bottlenecks, and RAG retrieval scores.
2. **FinOps / Engineering Lead:** Needs real-time token cost attribution per agent, per customer tenant, and hard budget kill-switches for infinite agent loops.
3. **Security Engineer:** Needs an IAM firewall for Model Context Protocol (MCP) servers-blocking unauthorized SQL writes, shell executions, or PII leaks, and queuing high-risk tool calls for human-in-the-loop (HITL) approval.

## 3. Core Functional Modules (MVP Scope - 100% Working Implementation Required)

### Module A: Live Telemetry & Trace Streamer (SSE)
- Real-time ingestion endpoint (`POST /api/v1/ingest/span`) accepting OpenTelemetry-compatible agent spans (`LLM_INFERENCE`, `MCP_TOOL_CALL`, `RAG_RETRIEVAL`, `GUARDRAIL_INTERCEPT`).
- Live Server-Sent Events (SSE) stream (`GET /api/v1/stream/events`) pushing active spans to the frontend with zero polling.
- Built-in **Live Traffic Simulator** toggle in the UI header that generates realistic multi-agent execution traces (e.g., "Autonomous Code Reviewer", "SQL Data Analyst Agent", "Customer Refund Agent") so the platform works out-of-the-box immediately upon launch.

### Module B: Interactive Trace Waterfall & Execution Inspector
- Filterable table of agent runs with status badges (`COMPLETED`, `RUNNING`, `BLOCKED`, `PENDING_HITL`, `LOOP_KILLED`), total tokens, cost in USD, latency (ms), and step count.
- Clicking a trace opens a split-pane **Execution Inspector**:
  - **Left Pane:** Hierarchical span waterfall timeline with relative duration bars and token breakdown.
  - **Right Pane:** Full JSON payload viewer (System Prompt, Input Arguments, MCP Tool Output, Token Cost math, and Guardrail Verdict).

### Module C: MCP Server Registry & Security Policy Firewall
- Protocol-aware MCP JSON-RPC 2.0 endpoint (`POST /api/v1/mcp/{server_name}/rpc`) so policies apply to agents that never import the SDK, with tool-manifest pinning and OWASP MCP03 rug-pull detection.
- Interactive registry of connected MCP servers (e.g., `postgres-prod-mcp`, `github-repo-mcp`, `filesystem-sandbox-mcp`, `stripe-billing-mcp`).
- Granular rule builder per MCP server:
  - **Permission Mode:** `READ_ONLY`, `HITL_REQUIRED`, `STRICT_BLOCK` (plus `ALLOW_ALL`).
  - **Regex / Semantic Guardrail:** Automatically blocks patterns like `DROP TABLE`, `rm -rf`, `sk_live_`, or SSN formats.
  - **Max Spend Per Run:** Hard USD cap (e.g., `$0.50` per session) and Max Recursive Depth (e.g., `12 steps`).

### Module D: Human-in-the-Loop (HITL) Escalation Queue
- When an agent triggers a `REQUIRE_HITL_APPROVAL` policy (e.g., attempting to execute a database mutation or issue a Stripe refund), the span pauses in `PENDING_APPROVAL` state.
- Operators can inspect the exact tool arguments in the UI and click **Approve Execution** or **Reject & Terminate Run** with an audit reason.

### Module E: FinOps Token & Latency Analytics Dashboard
- Top KPI cards: Total Spend (24h), Active Agent Sessions, Guardrail Interceptions, Mean Time to First Token (TTFT).
- Cost & Token Velocity visualization broken down by Model (`gpt-4o`, `claude-3-7-sonnet`, `gemini-2.5-pro`, `llama-3.3-70b`) and by Agent ID.

## 4. Non-Functional Requirements
- **Zero Mock Placeholders:** Every button, filter, modal, simulator toggle, and approval action must mutate actual SQLite/PostgreSQL database state via the FastAPI backend.
- **Deterministic Startup:** Single-command or dual-service startup with automatic database schema migration and rich initial seed data.