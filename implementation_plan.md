# Implementation Plan

[Overview]
Build AegisMCP — an Enterprise AI Agent Observability, FinOps Metering, and MCP Runtime Security Gateway — from scratch as a full-stack application with a FastAPI backend (Python 3.11+) and Next.js 15 frontend (React 19, TypeScript), orchestrated via Docker Compose. The backend exposes authenticated REST + SSE endpoints for telemetry ingestion, trace querying, MCP server policy management, HITL span decisions, and a live traffic simulator. The frontend implements an obsidian monochrome UI with automatic session bootstrapping, double-submit CSRF, SSE event streaming, and four navigation tabs (Live Trace Explorer, MCP Policy Firewall, HITL Approval Queue, FinOps Metrics). All UI actions mutate real SQLite database state via FastAPI — no mocks or stubs.

[Types]
Type system changes are detailed in the plan: Pydantic v2 schemas with ConfigDict(extra="forbid", str_strip_whitespace=True) for all request/response models; SQLAlchemy 2.0 ORM models for MCPServer, AgentTrace, TraceSpan; TypeScript interfaces matching Pydantic schemas in snake_case; Security types for SessionData, CsrfTokenPair, RateLimitEntry; GuardrailVerdict type for deterministic evaluation results.

[Files]
Backend: backend/Dockerfile, backend/requirements.txt, backend/app/__init__.py, backend/app/config.py, backend/app/database.py, backend/app/models.py, backend/app/schemas.py, backend/app/security.py, backend/app/main.py, backend/app/seed.py, backend/app/services/__init__.py, backend/app/services/guardrail_engine.py, backend/app/services/simulator.py, backend/app/services/sse_manager.py, backend/app/api/__init__.py, backend/app/api/routes.py
Frontend: frontend/Dockerfile, frontend/package.json, frontend/tsconfig.json, frontend/tailwind.config.ts, frontend/postcss.config.mjs, frontend/next.config.mjs, frontend/src/types/aegis.ts, frontend/src/lib/api.ts, frontend/src/lib/useAegisStream.ts, frontend/src/app/globals.css, frontend/src/app/layout.tsx, frontend/src/app/page.tsx, frontend/src/components/HeaderBar.tsx, frontend/src/components/TraceExplorer.tsx, frontend/src/components/PolicyFirewall.tsx, frontend/src/components/HitlQueue.tsx, frontend/src/components/FinOpsMetrics.tsx
Root: docker-compose.yml, README.md, implementation_plan.md

[Functions]
All functions are specified in the plan: backend factory create_app(), DB dependencies, JWT mint/verify, CSRF double-submit, rate limiter, security middleware, guardrail evaluator, simulator generator, SSE pub/sub, all 12 API endpoints; frontend api.ts bootstrapSession/getCsrfToken/request/createEventSource, useAegisStream hook, and 5 React components.

[Classes]
Backend classes: Settings, MCPServer, AgentTrace, TraceSpan, SecurityHeadersMiddleware, RateLimiter, GuardrailEngine, TraceSimulator, SSEManager; Frontend classes/components: AegisApiClient, HeaderBar, TraceExplorer, PolicyFirewall, HitlQueue, FinOpsMetrics.

[Dependencies]
Backend: fastapi, uvicorn[standard], sqlalchemy[asyncio], pydantic-settings, python-jose[cryptography], passlib[bcrypt], python-multipart, sse-starlette, httpx
Frontend: next, react, react-dom, typescript, tailwindcss, lucide-react, framer-motion, postcss, autoprefixer
Infrastructure: docker-compose.yml, Dockerfiles, SQLite

[Testing]
Backend: py_compile on all .py files, import check, database seeding verification, endpoint smoke tests, guardrail engine tests
Frontend: tsc --noEmit, npm run build, session bootstrapping, CSRF injection, SSE withCredentials, security badge
End-to-End: docker-compose up, simulate traffic, view traces, HITL approve/reject, SSE live updates

[Implementation Order]
Phase 1-12 as detailed in the plan document, from backend foundation through final self-test.