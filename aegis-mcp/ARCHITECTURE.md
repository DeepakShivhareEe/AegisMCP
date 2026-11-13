# System Architecture & Technical Specification: AegisMCP

## 1. Technology Stack
- **Frontend:** Next.js 15 (App Router), React 19, TypeScript (Strict Mode), Tailwind CSS, Lucide React icons, Framer Motion (subtle layout transitions).
- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (Async / Sync SQLite for zero-config local persistence, seamlessly swappable to PostgreSQL via `DATABASE_URL`), `sse-starlette` / FastAPI `StreamingResponse` for Server-Sent Events.
- **Containerization:** `docker-compose.yml` orchestrating both `backend` (port `8000`) and `frontend` (port `3000`).

## 2. Database Schema (`backend/app/models.py`)

### Table 1: `mcp_servers`
- `id`: String (UUID / slug, primary key)
- `name`: String (e.g., `postgres-prod-mcp`)
- `endpoint_url`: String
- `transport`: Enum (`stdio`, `sse`, `websocket`)
- `status`: Enum (`ONLINE`, `DEGRADED`, `OFFLINE`)
- `permission_mode`: Enum (`ALLOW_ALL`, `READ_ONLY`, `HITL_REQUIRED`, `STRICT_BLOCK`)
- `max_cost_usd_per_run`: Float (default `0.50`)
- `max_steps_per_run`: Integer (default `15`)
- `blocked_patterns`: JSON Array of strings (e.g., `["DROP TABLE", "DELETE FROM", "rm -rf"]`)
- `created_at`: DateTime

### Table 2: `agent_traces`
- `id`: String (Trace ID, e.g., `trc_9f8a7d6c`)
- `agent_name`: String (e.g., `sql-analyst-v2`, `pr-sec-auditor`)
- `environment`: String (`production`, `staging`)
- `status`: Enum (`RUNNING`, `COMPLETED`, `BLOCKED`, `PENDING_HITL`, `LOOP_KILLED`)
- `total_tokens`: Integer
- `prompt_tokens`: Integer
- `completion_tokens`: Integer
- `total_cost_usd`: Float
- `total_latency_ms`: Integer
- `step_count`: Integer
- `started_at`: DateTime
- `ended_at`: DateTime (nullable)

### Table 3: `trace_spans`
- `id`: String (Span ID, e.g., `spn_1a2b3c4d`)
- `trace_id`: ForeignKey(`agent_traces.id`)
- `parent_span_id`: String (nullable)
- `step_index`: Integer
- `span_type`: Enum (`LLM_INFERENCE`, `MCP_TOOL_CALL`, `RAG_RETRIEVAL`, `GUARDRAIL_INTERCEPT`)
- `name`: String (e.g., `claude-3-7-sonnet`, `mcp:postgres:execute_query`)
- `model_or_server`: String
- `status`: Enum (`OK`, `BLOCKED`, `PENDING_APPROVAL`, `ERROR`)
- `latency_ms`: Integer
- `tokens_used`: Integer
- `cost_usd`: Float
- `input_payload`: JSON
- `output_payload`: JSON
- `guardrail_reason`: String (nullable)
- `created_at`: DateTime

## 3. REST & SSE API Contract (`backend/app/api/routes.py`)
1. `GET /api/v1/health` -> System health & DB status.
2. `GET /api/v1/analytics/summary` -> Aggregated FinOps metrics, model cost breakdown, and hourly token series.
3. `GET /api/v1/traces` -> Query params: `status`, `agent_name`, `search`, `limit`. Returns traces ordered by `started_at DESC`.
4. `GET /api/v1/traces/{trace_id}` -> Returns trace metadata + ordered `trace_spans` array.
5. `POST /api/v1/ingest/span` -> Evaluates span against active `mcp_servers` guardrail rules, calculates token cost, updates parent `agent_trace`, and broadcasts event to SSE subscribers.
6. `POST /api/v1/simulator/trigger` -> Generates a realistic 4-to-7 step multi-agent workflow (including normal completions, guardrail blocks, and HITL escalations) for live demonstration.
7. `GET /api/v1/mcp-servers` -> Lists all registered MCP servers and their active security policies.
8. `PATCH /api/v1/mcp-servers/{server_id}` -> Updates `permission_mode`, `max_cost_usd_per_run`, `max_steps_per_run`, or `blocked_patterns`.
9. `POST /api/v1/spans/{span_id}/decision` -> Payload: `{"action": "APPROVE" | "REJECT", "reviewer_note": "..."}`. Resolves `PENDING_APPROVAL` spans and updates trace status.
10. `GET /api/v1/stream/events` -> Server-Sent Events (SSE) endpoint streaming real-time trace updates to the Next.js frontend.