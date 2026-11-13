# Deterministic Implementation Plan & Target File Tree

## Target Repository File Tree
Build the exact structure below:

```text
aegis-mcp/
ÃÄÄ PRD.md
ÃÄÄ ARCHITECTURE.md
ÃÄÄ DESIGN_SYSTEM.md
ÃÄÄ AGENT_SKILLS.md
ÃÄÄ IMPLEMENTATION_PLAN.md
ÃÄÄ docker-compose.yml
ÃÄÄ README.md
ÃÄÄ backend/
³   ÃÄÄ Dockerfile
³   ÃÄÄ requirements.txt
³   ÀÄÄ app/
³       ÃÄÄ __init__.py
³       ÃÄÄ main.py                 # FastAPI app, CORS, startup seed hook
³       ÃÄÄ database.py             # SQLAlchemy engine & session dependency
³       ÃÄÄ models.py               # ORM models: MCPServer, AgentTrace, TraceSpan
³       ÃÄÄ schemas.py              # Pydantic v2 request/response schemas
³       ÃÄÄ seed.py                 # Rich initial seed data (4 MCP servers, 6 realistic traces)
³       ÃÄÄ services/
³       ³   ÃÄÄ __init__.py
³       ³   ÃÄÄ guardrail_engine.py # Cost, step-limit, regex & HITL policy evaluator
³       ³   ÃÄÄ simulator.py        # Multi-step realistic agent trace generator
³       ³   ÀÄÄ sse_manager.py      # Async pub/sub broadcaster for SSE clients
³       ÀÄÄ api/
³           ÃÄÄ __init__.py
³           ÀÄÄ routes.py           # All REST + SSE endpoints
ÀÄÄ frontend/
    ÃÄÄ Dockerfile
    ÃÄÄ package.json
    ÃÄÄ tsconfig.json
    ÃÄÄ tailwind.config.ts
    ÃÄÄ postcss.config.mjs
    ÃÄÄ next.config.mjs
    ÀÄÄ src/
        ÃÄÄ types/
        ³   ÀÄÄ aegis.ts            # Strict TypeScript interfaces matching Pydantic schemas
        ÃÄÄ lib/
        ³   ÀÄÄ api.ts              # Typed REST client + SSE connection helper
        ÃÄÄ app/
        ³   ÃÄÄ globals.css         # Obsidian monochrome variables & custom scrollbars
        ³   ÃÄÄ layout.tsx          # Root layout with Inter + JetBrains Mono fonts
        ³   ÀÄÄ page.tsx            # Master control plane dashboard
        ÀÄÄ components/
            ÃÄÄ HeaderBar.tsx       # Live status, Simulator trigger, KPI pills
            ÃÄÄ TraceExplorer.tsx   # Filterable trace table + split-pane waterfall & JSON inspector
            ÃÄÄ PolicyFirewall.tsx  # Interactive MCP Server guardrail editor & pattern manager
            ÃÄÄ HitlQueue.tsx       # Human-in-the-loop approval/rejection workbench
            ÀÄÄ FinOpsMetrics.tsx   # Cost attribution, model breakdown & circuit breaker telemetry