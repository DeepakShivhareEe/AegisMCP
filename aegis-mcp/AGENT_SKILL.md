# Autonomous Coding Agent Skills & Execution Rules

## Skill 1: Full-Stack Contract Synchronization
- Before writing any frontend fetch logic, verify the exact Pydantic schema in `backend/app/schemas.py`.
- Every API response field in Python (`snake_case`) must be cleanly typed in TypeScript (`frontend/src/types/aegis.ts`).
- Never leave `TODO`, `// implement later`, or mock `setTimeout` stubs in the frontend. All actions must hit the FastAPI backend.

## Skill 2: Resilient SSE & Real-Time State Management
- Use native browser `EventSource` in a dedicated React hook (`useAegisStream.ts`) connected to `NEXT_PUBLIC_API_URL/api/v1/stream/events`.
- Include automatic reconnection backoff if the backend restarts and provide an instant fallback refresh function so the UI remains 100% responsive at all times.

## Skill 3: Deterministic Guardrail & Cost Engine
- In `backend/app/services/guardrail_engine.py`, implement real deterministic evaluation:
  1. Check if `trace.total_cost_usd + span.cost_usd > server.max_cost_usd_per_run`. If exceeded, mark span `BLOCKED` and trace `LOOP_KILLED`.
  2. Check if `trace.step_count + 1 > server.max_steps_per_run`. If exceeded, mark trace `LOOP_KILLED`.
  3. Scan serialized `input_payload` against `server.blocked_patterns` (case-insensitive substring & regex match). If matched, mark span `BLOCKED` with exact rule violation message.
  4. If `server.permission_mode == "HITL_REQUIRED"` and `span.span_type == "MCP_TOOL_CALL"`, mark span `PENDING_APPROVAL` and trace `PENDING_HITL`.

## Skill 4: Self-Verification & Zero-Error Build Protocol
- After generating backend files, run `python3 -m py_compile` on all Python modules and verify FastAPI boots cleanly.
- After generating frontend files, run `npm run build` (or `npx tsc --noEmit`) to verify zero TypeScript compilation or missing import errors.
- Fix any linter, type, or runtime errors autonomously before concluding the build.