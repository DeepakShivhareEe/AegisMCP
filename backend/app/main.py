"""FastAPI application factory for AegisMCP."""

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import routes
from app.config import settings
from app.database import get_db, init_db
from app.schemas import HealthResponse
from app.security import (
    SecurityHeadersMiddleware,
    rate_limit_middleware,
    rate_limit_service,
)
from app.seed import seed_database
from app.services.events import sse_manager

logger = logging.getLogger("aegis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and seed data on startup."""
    try:
        await init_db()
        await seed_database()
        await sse_manager.start()
        await rate_limit_service.start(settings.REDIS_URL)
        logger.info(
            "Database initialized (environment=%s, seeding=%s)",
            settings.ENVIRONMENT,
            "enabled"
            if settings.ENVIRONMENT.strip().lower() == "development"
            else "disabled",
        )
    except Exception:
        logger.exception("Database initialization failed")
        raise
    try:
        yield
    finally:
        await sse_manager.stop()
        await rate_limit_service.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="AegisMCP", version="1.0.0", lifespan=lifespan)

    # Security headers middleware (outermost)
    app.add_middleware(SecurityHeadersMiddleware)

    # Rate limiting middleware
    app.middleware("http")(rate_limit_middleware)

    # CORS middleware - strict origins, never wildcard with credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "X-CSRF-Token",
            "X-Aegis-API-Key",
            "X-Request-ID",
            "Accept",
            "Cache-Control",
        ],
        expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
        max_age=600,
    )

    # Global Exception Handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": detail_msg,
                "detail": exc.detail,
                "status_code": exc.status_code,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Return a 422 without echoing the submitted payload back verbatim."""
        errors = [
            {
                "loc": [str(part) for part in error.get("loc", [])],
                "msg": error.get("msg", "Invalid value"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "Validation failed",
                "detail": errors,
                "status_code": 422,
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal Server Error",
                "detail": "An unexpected error occurred while processing your request.",
                "status_code": 500,
            },
        )

    # Include API routes
    app.include_router(routes.router, prefix="/api/v1")

    # Root health check and index endpoints
    @app.get("/health", response_model=HealthResponse, tags=["Health"])
    async def root_health(db: Annotated[AsyncSession, Depends(get_db)]) -> HealthResponse:
        """Root health check for monitoring, Docker HEALTHCHECK, and load balancers."""
        return await routes.health(db)

    @app.get("/", tags=["Root"])
    async def root_index() -> dict[str, str]:
        """Root service index."""
        return {
            "service": "AegisMCP Gateway",
            "version": "1.0.0",
            "status": "online",
            "health": "/health",
            "api_v1_health": "/api/v1/health",
            "docs": "/docs",
        }

    # OpenAI-compatible models endpoint for SDK auto-discovery
    @app.get("/v1/models", tags=["OpenAI Compatibility"])
    async def list_models() -> dict[str, Any]:
        """OpenAI-compatible models endpoint."""
        return {"data": [], "object": "list"}

    return app


app = create_app()
