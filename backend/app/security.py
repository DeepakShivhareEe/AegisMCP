"""Security primitives: JWT sessions, double-submit CSRF, API keys, rate limits, headers."""

import hashlib
import hmac
import logging
import secrets
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.models import APIKey

logger = logging.getLogger(__name__)


def is_production() -> bool:
    """Single source of truth for the production security posture."""
    return settings.ENVIRONMENT.strip().lower() == "production"


def cookie_security_flags() -> dict[str, Any]:
    """Cookie attributes for the session and CSRF cookies.

    Production runs the console and API on different sites (for example
    Vercel + Render), so cross-site cookies require ``SameSite=None`` paired
    with ``Secure``. Development keeps ``Lax`` over plain HTTP so localhost
    keeps working without TLS.
    """
    production = is_production()
    return {
        "samesite": "none" if production else "lax",
        "secure": production,
        "httponly_session": True,
    }

# Swagger/ReDoc load their assets from a CDN, so they keep a relaxed policy.
_DOCUMENTATION_PATHS = ("/docs", "/redoc", "/openapi.json")

API_CSP = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)
DOCS_CSP = (
    "default-src 'self' https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)


def mint_session_token(operator_id: str, org_id: str, role: str) -> str:
    """Mint an HS256 JWT session token."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES)
    payload: dict[str, Any] = {
        "sub": operator_id,
        "org_id": org_id,
        "role": role,
        "jti": secrets.token_urlsafe(16),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_session_token(token: str) -> dict[str, Any] | None:
    """Verify a JWT session token and return its payload, or None if invalid."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_signature": True, "verify_exp": True, "verify_aud": False},
        )
    except JWTError:
        return None
    if not isinstance(payload.get("sub"), str) or not payload.get("sub"):
        return None
    if not isinstance(payload.get("org_id"), str) or not payload.get("org_id"):
        return None
    return payload


def generate_csrf_token() -> str:
    """Generate a random CSRF token."""
    return secrets.token_urlsafe(32)


def verify_csrf_double_submit(cookie_token: str | None, header_token: str | None) -> bool:
    """Constant-time comparison of the CSRF cookie against the request header."""
    if not cookie_token or not header_token:
        return False
    if not isinstance(cookie_token, str) or not isinstance(header_token, str):
        return False
    return hmac.compare_digest(cookie_token.encode("utf-8"), header_token.encode("utf-8"))


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of the secret portion of an API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def split_api_key(api_key: str) -> tuple[str | None, str]:
    """Split ``aegis_live_<prefix8>_<secret>`` into (key_prefix, secret).

    Returns ``(None, api_key)`` for keys that do not follow the generated
    format (for example a legacy env-configured static key).
    """
    parts = api_key.split("_", 3)
    if len(parts) == 4 and parts[0] == "aegis" and parts[1] == "live":
        return f"{parts[0]}_{parts[1]}_{parts[2]}", parts[3]
    return None, api_key


async def verify_api_key_db(api_key: str, db: AsyncSession) -> dict[str, Any] | None:
    """Verify an X-Aegis-API-Key against database-stored hashes.

    Lookup is by the non-secret ``key_prefix``; the hash itself is then checked
    with ``hmac.compare_digest`` so the comparison is constant time.
    """
    if not api_key or not isinstance(api_key, str):
        return None

    prefix, raw_part = split_api_key(api_key)
    key_hash = hash_api_key(raw_part)

    if prefix:
        result = await db.execute(
            select(APIKey).where(
                APIKey.key_prefix == prefix,
                APIKey.is_active.is_(True),
            )
        )
    else:
        result = await db.execute(
            select(APIKey).where(
                APIKey.key_hash == key_hash,
                APIKey.is_active.is_(True),
            )
        )

    candidates = list(result.scalars().all())
    matched = next(
        (candidate for candidate in candidates
         if hmac.compare_digest(candidate.key_hash, key_hash)),
        None,
    )
    if matched is None:
        return None

    matched.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "sub": f"api-key:{matched.id}",
        "org_id": matched.org_id or settings.DEFAULT_ORG_ID,
        "role": "admin",
        "auth_type": "api_key",
    }


def verify_api_key(api_key: str | None) -> bool:
    """Constant-time check of a static machine key against API_KEY_HASH."""
    if not api_key or not settings.API_KEY_HASH:
        return False
    key_hash = hash_api_key(api_key)
    return hmac.compare_digest(key_hash, settings.API_KEY_HASH)


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key: returns (raw_key, key_prefix, key_hash)."""
    raw = secrets.token_hex(32)
    prefix = f"aegis_live_{raw[:8]}"
    return f"{prefix}_{raw}", prefix, hash_api_key(raw)


class RateLimiter:
    """In-memory sliding-window rate limiter with bounded client tracking."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        max_tracked_clients: int = 10_000,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_tracked_clients = max_tracked_clients
        self._windows: dict[str, deque[float]] = {}

    def _prune(self, window: deque[float], now: float) -> None:
        window_start = now - self.window_seconds
        while window and window[0] < window_start:
            window.popleft()

    def _evict_idle(self, now: float) -> None:
        """Drop windows with no activity inside the current window."""
        if len(self._windows) <= self.max_tracked_clients:
            return
        window_start = now - self.window_seconds
        for client_id in [
            key for key, window in self._windows.items()
            if not window or window[-1] < window_start
        ]:
            self._windows.pop(client_id, None)

    def remaining(self, client_id: str) -> int:
        """Current quota left for a client without consuming a request."""
        now = time.time()
        window = self._windows.get(client_id)
        if window is None:
            return self.max_requests
        self._prune(window, now)
        return max(0, self.max_requests - len(window))

    def is_allowed(self, client_id: str) -> tuple[bool, int]:
        now = time.time()
        self._evict_idle(now)

        window = self._windows.setdefault(client_id, deque())
        self._prune(window, now)

        if len(window) >= self.max_requests:
            return False, 0

        window.append(now)
        return True, self.max_requests - len(window)


rate_limiter = RateLimiter(
    max_requests=settings.RATE_LIMIT_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
)


def verify_bootstrap_token(provided: str | None) -> bool:
    """Check the optional console bootstrap secret in constant time."""
    if not settings.AEGIS_BOOTSTRAP_TOKEN:
        return True
    if not provided:
        return False
    return hmac.compare_digest(
        provided.encode("utf-8"), settings.AEGIS_BOOTSTRAP_TOKEN.encode("utf-8")
    )


class RateLimitService:
    """Distributed rate limiter: Redis counters when configured, else in-process.

    Redis uses a fixed window keyed by client and window index. Any broker error
    falls back to the local limiter rather than failing the request, so a Redis
    outage degrades quota accuracy instead of availability.
    """

    def __init__(self, local: RateLimiter) -> None:
        self._local = local
        self._redis: Any = None
        self.max_requests = local.max_requests
        self.window_seconds = local.window_seconds

    @property
    def redis_enabled(self) -> bool:
        return self._redis is not None

    async def start(self, redis_url: str) -> None:
        if not redis_url or self._redis is not None:
            return
        try:
            import redis.asyncio as redis_asyncio  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "REDIS_URL is set but the 'redis' package is not installed; "
                "rate limiting stays in-process"
            )
            return
        client = redis_asyncio.from_url(redis_url, decode_responses=True)
        try:
            await client.ping()
        except Exception as exc:  # noqa: BLE001 - degrade instead of failing startup
            logger.warning("Redis unavailable (%s); rate limiting stays in-process", exc)
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass
            return
        self._redis = client
        logger.info("Distributed rate limiting enabled through Redis")

    async def stop(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._redis = None

    def _key(self, client_id: str) -> str:
        window_index = int(time.time()) // self.window_seconds
        return f"aegis:rl:{client_id}:{window_index}"

    async def allow(self, client_id: str) -> tuple[bool, int]:
        if self._redis is not None:
            try:
                key = self._key(client_id)
                count = int(await self._redis.incr(key))
                if count == 1:
                    await self._redis.expire(key, self.window_seconds)
                return count <= self.max_requests, max(0, self.max_requests - count)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis rate limit failed (%s); using local limiter", exc)
        return self._local.is_allowed(client_id)

    async def remaining(self, client_id: str) -> int:
        if self._redis is not None:
            try:
                used = int(await self._redis.get(self._key(client_id)) or 0)
                return max(0, self.max_requests - used)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis rate limit read failed (%s); using local limiter", exc)
        return self._local.remaining(client_id)


rate_limit_service = RateLimitService(rate_limiter)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds hardening headers and X-Request-ID to every response."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or secrets.token_urlsafe(8)

        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Request-ID"] = request_id
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )

        is_docs = request.url.path in _DOCUMENTATION_PATHS
        response.headers["Content-Security-Policy"] = DOCS_CSP if is_docs else API_CSP

        if is_production():
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response


_RATE_LIMIT_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")
_RATE_LIMIT_EXEMPT_PATHS = ("/", "/health")


async def rate_limit_middleware(request: Request, call_next):
    """Per-client sliding-window limiter applied to API traffic only."""
    path = request.url.path
    if path in _RATE_LIMIT_EXEMPT_PATHS or path.startswith(_RATE_LIMIT_EXEMPT_PREFIXES):
        return await call_next(request)

    client_id = request.client.host if request.client else "unknown"
    allowed, remaining = await rate_limit_service.allow(client_id)

    if not allowed:
        request_id = request.headers.get("X-Request-ID") or secrets.token_urlsafe(8)
        return JSONResponse(
            status_code=429,
            content={
                "error": "Too Many Requests",
                "detail": "Rate limit exceeded",
                "status_code": 429,
            },
            headers={
                "X-RateLimit-Remaining": "0",
                "X-Request-ID": request_id,
                "Retry-After": str(settings.RATE_LIMIT_WINDOW_SECONDS),
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response
