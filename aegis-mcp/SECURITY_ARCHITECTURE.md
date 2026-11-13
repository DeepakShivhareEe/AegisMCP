# Production Security, CORS, Cookie & Cryptography Specification: AegisMCP

## 1. Zero-Trust Authentication & Dual-Cookie CSRF Architecture
AegisMCP uses a hardened **HttpOnly Session Cookie + Double-Submit CSRF Token** architecture for browser operators, plus **Constant-Time API Key Verification** for machine-to-machine span ingestion.

### 1.1 Cookie Specifications (`POST /api/v1/auth/session`)
To ensure immediate zero-friction local testing while enforcing real production security, provide a `POST /api/v1/auth/session` endpoint (auto-bootstrapped on frontend initialization or via the Operator Login modal) that issues two cookies:
1. **`aegis_session` (Session JWT Cookie):**
   - `httponly=True` (Blocks XSS `document.cookie` theft)
   - `samesite="lax"` (Prevents cross-site top-level POST forgery while working seamlessly across `localhost:3000` -> `localhost:8000`)
   - `secure=True` when `ENVIRONMENT == "production"`, `False` on `localhost` HTTP
   - `path="/"`
   - `max_age=1800` (30 minutes)
   - **JWT Payload:** Signed with `HS256` (pinned algorithm in verification-never allow `none` or algorithm confusion), containing `sub` (operator ID), `org_id` (tenant isolation for BOLA prevention), `role` (`admin` | `auditor`), `jti` (unique token ID), `iat`, and `exp`.
2. **`aegis_csrf` (CSRF Double-Submit Cookie):**
   - `httponly=False` (JavaScript reads this cookie and attaches it as the `X-CSRF-Token` request header)
   - `samesite="lax"`
   - `secure=True` when `ENVIRONMENT == "production"`
   - Generated via `secrets.token_urlsafe(32)`.

### 1.2 CSRF & Auth Dependency Enforcement (`backend/app/security.py`)
- All state-mutating routes (`POST /api/v1/mcp-servers/...`, `PATCH /api/v1/mcp-servers/{id}`, `POST /api/v1/spans/{id}/decision`, `POST /api/v1/simulator/trigger`) MUST verify:
  1. Valid `aegis_session` cookie JWT signature and expiration.
  2. Constant-time comparison (` hmac.compare_digest(cookie_csrf, header_csrf)`) between the `aegis_csrf` cookie and the `X-CSRF-Token` HTTP header.
- Machine ingestion route (`POST /api/v1/ingest/span`) supports either the Operator Session + CSRF OR an `X-Aegis-API-Key` header verified via `hmac.compare_digest` against a SHA-256 hashed key.

## 2. Strict CORS Configuration (`backend/app/main.py`)
NEVER combine `allow_origins=["*"]` with `allow_credentials=True`. Configure `CORSMiddleware` explicitly:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,  # ["http://localhost:3000", "[http://127.0.0.1:3000](http://127.0.0.1:3000)"]
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Aegis-API-Key", "Accept", "Cache-Control"],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
    max_age=600,
)