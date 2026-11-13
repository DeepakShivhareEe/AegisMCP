# AegisMCP

Enterprise AI Agent Observability, FinOps Metering, and MCP Runtime Security Gateway.

## Architecture

- **Backend:** FastAPI (Python 3.11+) with SQLAlchemy 2.0, SQLite, JWT session cookies, double-submit CSRF, sliding-window rate limiting, SSE event streaming
- **Frontend:** Next.js 15, React 19, TypeScript, Tailwind CSS (obsidian monochrome design system)
- **Infrastructure:** Docker Compose orchestrating backend (port 8000) and frontend (port 3000)

## Quick Start

### Using Docker Compose

```bash
docker-compose up --build
```

- Backend API: http://localhost:8000
- Frontend UI: http://localhost:3000
- API docs: http://localhost:8000/docs

### Local Development

**Backend:**
```bash
cd backend
pip install -r requirements.txt
py -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Security Features

- HttpOnly JWT session cookies (`aegis_session`)
- Double-submit CSRF protection (`aegis_csrf` cookie + `X-CSRF-Token` header)
- Constant-time API key verification (`X-Aegis-API-Key`)
- SecurityHeadersMiddleware (CSP, X-Frame-Options, etc.)
- Sliding-window rate limiting (429 Too Many Requests)
- Strict CORS (no wildcard with credentials)
- Pydantic v2 strict validation (`extra="forbid"`, sanitized 422 responses)
- Organization-scoped traces, spans and API keys (cross-tenant reads return 404)
- Bounded, ReDoS-resistant guardrail regex evaluation (length caps, no nested quantifiers, off-loop execution)
- Guardrails evaluated **before** guarded tool code runs (SDK pre-flight)
- MCP tool-manifest pinning with OWASP MCP03 rug-pull and tool-poisoning detection
- Output screening for indirect prompt injection plus deterministic PII/secret redaction before storage or SSE
- Separation of duties on HITL approvals, `admin`/`auditor` role scoping, optional `AEGIS_BOOTSTRAP_TOKEN`
- Optional `REDIS_URL` for multi-worker SSE fan-out and distributed rate limiting

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/v1/health | System health |
| POST | /api/v1/mcp/{server}/rpc | MCP JSON-RPC 2.0 gateway (pinning, interception, output screening) |
| POST | /api/v1/mcp-servers/{id}/tools/reset | Clear the pinned tool manifest (admin) |
| POST | /api/v1/otlp/v1/traces | OpenTelemetry OTLP/HTTP JSON trace ingest |
| POST | /api/v1/auth/session | Mint session + CSRF cookies |
| GET | /api/v1/auth/me | Current operator session |
| GET | /api/v1/traces | List traces (org-scoped) |
| GET | /api/v1/traces/{id} | Trace detail + spans |
| POST | /api/v1/ingest/span | Ingest span + guardrail eval |
| POST | /api/v1/proxy/intercept | Pre-flight verdict for an agent call (API key) |
| POST | /api/v1/spans/{id}/complete | Attach output/usage after execution (API key) |
| GET | /api/v1/spans/{id}/status | Poll span status for HITL (API key) |
| POST | /api/v1/simulator/trigger | Generate demo trace |
| GET | /api/v1/mcp-servers | List MCP servers |
| PATCH | /api/v1/mcp-servers/{id} | Update security policy |
| POST | /api/v1/spans/{id}/decision | HITL approve/reject |
| GET | /api/v1/hitl/pending | Pending HITL queue |
| GET | /api/v1/api-keys | List API keys |
| POST | /api/v1/api-keys | Create API key (raw key returned once) |
| DELETE | /api/v1/api-keys/{id} | Revoke API key |
| GET | /api/v1/analytics/summary | FinOps metrics |
| GET | /api/v1/stream/events | SSE event stream |

All data endpoints require an `aegis_session` cookie or `X-Aegis-API-Key`; browser
mutations additionally require the `X-CSRF-Token` header.

## Python SDK

`guard_tool` authorises the call before running it, so a blocked tool never
executes, and HITL calls wait for an operator decision first:

```python
from aegis_sdk import AegisClient

client = AegisClient(api_key="aegis_live_...", base_url="http://localhost:8000")

@client.guard_tool("postgres-prod-mcp", "execute_query")
def run_query(sql: str):
    return db.execute(sql)   # not reached when the call is blocked

with client.intercept(
    "stripe-billing-mcp", "create_refund", input_payload={"amount": 45000}
) as ctx:
    result = stripe.Refund.create(amount=45000)
    ctx.set_output({"refund_id": result.id})
```

After the tool body finishes, the SDK reports output, latency, tokens and cost
to `/api/v1/spans/{id}/complete`. Run `py examples/real_agent_test.py` with
`AEGIS_API_KEY` set for a three-scenario demo.

## MCP gateway (JSON-RPC 2.0)

Point an MCP client at `POST /api/v1/mcp/{server_name}/rpc` with an API key. The
gateway speaks `initialize`, `ping`, `tools/list` and `tools/call`:

- `tools/list` pins a SHA-256 of the canonical tool manifest on first discovery.
  A later manifest change is rejected with JSON-RPC error `-32005`
  (`OWASP_MCP03_RUG_PULL_DETECTED`) until an admin calls
  `POST /api/v1/mcp-servers/{id}/tools/reset`. Hidden instructions in tool
  descriptions are rejected with `-32004` (`OWASP_MCP03_TOOL_POISONING`).
- `tools/call` runs the guardrail engine **before** the upstream server is
  invoked: `-32001` blocked, `-32002` loop-killed, `-32003` pending HITL
  (poll `/api/v1/spans/{id}/status`). Allowed results are screened for indirect
  prompt injection (`-32006`) and secrets/PII are redacted before the result is
  returned and before it is stored.
- Seeded demo servers (`*.internal` endpoints) are served from a deterministic
  in-process catalog; real endpoints are forwarded over HTTP with
  `MCP_UPSTREAM_TIMEOUT_SECONDS`.

## OpenTelemetry

`POST /api/v1/otlp/v1/traces` accepts OTLP/HTTP JSON authenticated with
`X-Aegis-API-Key` or `Authorization: Bearer <api_key>` and maps `gen_ai.*`
attributes (`gen_ai.request.model`, `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, `gen_ai.prompt`, `gen_ai.completion`) and
`mcp.tool.name` into traces and spans. Point any OTel exporter at it:

```bash
OTEL_EXPORTER_OTLP_PROTOCOL=http/json
OTEL_EXPORTER_OTLP_ENDPOINT=https://aegis.example.com
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer aegis_live_..."
```

## TypeScript SDK

```ts
import { AegisClient } from "./sdk/aegis-sdk";

const client = new AegisClient({ apiKey: process.env.AEGIS_API_KEY!, baseUrl: "http://localhost:8000" });

// Authorises before running: a blocked call never executes.
const rows = await client.guardTool("postgres-prod-mcp", "execute_query", () => db.query(sql), {
  inputPayload: { sql },
});

// Protocol-level tools/call through the gateway (pinning + screening).
const reply = await client.mcpRpc("filesystem-sandbox-mcp", "tools/call", {
  name: "read_file",
  arguments: { path: "/workspace/notes.md" },
});
```

## Operations notes

- HITL approvals enforce separation of duties: the principal that created a
  span cannot approve it (`ALLOW_SELF_APPROVAL=true` only for single-operator
  demos). `auditor` sessions are read-only.
- Set `AEGIS_BOOTSTRAP_TOKEN` to require a shared secret on `/auth/session`
  when the console is not fronted by an identity provider.
- Set `REDIS_URL` before scaling past one backend worker, and pair it with
  `WEB_CONCURRENCY` (Docker Compose exposes both). Without Redis the SSE
  broadcaster and rate limiter are per-process.
- `NEXT_PUBLIC_API_URL` is a **build** argument for the frontend image; it is
  inlined at `next build` time.
