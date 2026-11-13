"""Pydantic Settings configuration for AegisMCP backend."""

import json
import re
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
)

DEV_SECRET_KEY = "dev-secret-key-change-in-production"

# Values that must never sign a production session token.
INSECURE_SECRET_VALUES = frozenset(
    {
        DEV_SECRET_KEY,
        "changeme",
        "change-me",
        "change-me-in-production",
        "secret",
        "secret-key",
        "supersecret",
        "password",
        "insecure",
        "test",
        "testing",
        "your-secret-key",
        "your-secret-key-here",
        "aegis-dev-secret",
        "dev-secret",
        "dev-secret-key",
    }
)

_LOCAL_HOST_MARKERS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
_ORG_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class _LenientEnvSource(EnvSettingsSource):
    """Leave complex values undecoded so a validator can accept CSV or JSON."""

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        return value


class _LenientDotEnvSource(DotEnvSettingsSource):
    """Same as above, for values read from the .env file."""

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        return value


class Settings(BaseSettings):
    """Application settings loaded from environment variables with sensible defaults."""

    SECRET_KEY: str = Field(default=DEV_SECRET_KEY, min_length=32)
    ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    ENVIRONMENT: str = Field(default="development")
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./aegis.db")
    API_KEY_HASH: str = Field(default="")
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_EXPIRATION_MINUTES: int = Field(default=30, ge=1, le=1440)
    RATE_LIMIT_REQUESTS: int = Field(default=100, ge=1)
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=1)

    # --- Tenancy -----------------------------------------------------------
    # Every trace and API key is scoped to an organization. Sessions can only
    # be minted for an organization in ALLOWED_ORG_IDS; anything else is
    # clamped to DEFAULT_ORG_ID so a caller can never claim another tenant.
    DEFAULT_ORG_ID: str = Field(default="org-1")
    ALLOWED_ORG_IDS: list[str] = Field(default=["org-1"])

    # Session bootstrap is a development convenience (this project has no
    # external IdP). Disable it in production to stop unauthenticated identity
    # minting.
    ALLOW_SESSION_BOOTSTRAP: bool = Field(default=True)

    # Optional fixed API key seeded on first run (aegis_live_<8hex>_<64hex>).
    # Useful for CI/demo scripts instead of copying a key out of the UI.
    SEED_API_KEY: str = Field(default="")

    # Optional shared secret required by /auth/session when set. Production
    # deployments front the console with an IdP or an SSO proxy that holds it.
    AEGIS_BOOTSTRAP_TOKEN: str = Field(default="")

    # Separation of duties: a reviewer may not approve their own HITL request.
    # Only enable this for single-operator demos.
    ALLOW_SELF_APPROVAL: bool = Field(default=False)

    # Optional Redis for multi-worker SSE fan-out and distributed rate limits.
    # When empty, the bounded in-process implementations are used.
    REDIS_URL: str = Field(default="")

    # Upstream MCP server timeout and OTLP payload bounds.
    MCP_UPSTREAM_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0, le=120)
    OTLP_MAX_SPANS: int = Field(default=5000, ge=1, le=100_000)

    # A shared .env also carries SDK/demo variables (AEGIS_API_KEY,
    # AEGIS_BASE_URL, provider keys). Unknown keys are ignored here; request
    # and response schemas remain strict (extra="forbid").
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _LenientEnvSource(settings_cls),
            _LenientDotEnvSource(
                settings_cls,
                env_file=settings_cls.model_config.get("env_file"),
                env_file_encoding=settings_cls.model_config.get("env_file_encoding"),
            ),
            file_secret_settings,
        )

    @field_validator("ALLOWED_ORIGINS", "ALLOWED_ORG_IDS", mode="before")
    @classmethod
    def _parse_list_values(cls, value: Any) -> Any:
        """Accept JSON arrays and comma-separated strings from env files."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return parsed
        return [part.strip().strip('"').strip("'") for part in text.split(",") if part.strip()]

    @property
    def is_production(self) -> bool:
        """True when running with production security posture."""
        return self.ENVIRONMENT.strip().lower() == "production"

    @model_validator(mode="after")
    def _validate_security_posture(self) -> "Settings":
        if not _ORG_ID_PATTERN.match(self.DEFAULT_ORG_ID):
            raise ValueError("DEFAULT_ORG_ID must match ^[A-Za-z0-9_-]{1,64}$")
        for org_id in self.ALLOWED_ORG_IDS:
            if not _ORG_ID_PATTERN.match(org_id):
                raise ValueError("ALLOWED_ORG_IDS entries must match ^[A-Za-z0-9_-]{1,64}$")
        if self.is_production:
            # Refuse to boot with a weak or well-known signing key: a stolen or
            # guessed SECRET_KEY forges every session cookie.
            secret = (self.SECRET_KEY or "").strip()
            if secret.lower() in INSECURE_SECRET_VALUES:
                raise ValueError(
                    "SECRET_KEY is a known placeholder; set a unique random value "
                    "when ENVIRONMENT=production"
                )
            if len(secret) < 32:
                raise ValueError(
                    "SECRET_KEY must be at least 32 characters when ENVIRONMENT=production"
                )

            # Cookies are SameSite=None+Secure in production, so the frontend
            # origin must be pinned explicitly and served over TLS.
            if not self.ALLOWED_ORIGINS:
                raise ValueError(
                    "ALLOWED_ORIGINS must list the production frontend origin(s) "
                    "when ENVIRONMENT=production"
                )
            if "*" in self.ALLOWED_ORIGINS:
                raise ValueError(
                    "ALLOWED_ORIGINS must not contain '*' when credentials are allowed"
                )
            for origin in self.ALLOWED_ORIGINS:
                if not origin.startswith("https://"):
                    raise ValueError(
                        f"ALLOWED_ORIGINS entry {origin!r} must use https:// in production"
                    )
                if any(marker in origin for marker in _LOCAL_HOST_MARKERS):
                    raise ValueError(
                        f"ALLOWED_ORIGINS entry {origin!r} cannot be a loopback origin "
                        "in production"
                    )
        return self


settings = Settings()
