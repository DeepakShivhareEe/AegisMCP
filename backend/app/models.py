"""SQLAlchemy ORM models for AegisMCP."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings
from app.enums import (
    PermissionMode,
    ServerStatus,
    SpanStatus,
    SpanType,
    TraceStatus,
    TransportType,
)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(500), nullable=False)
    transport: Mapped[TransportType] = mapped_column(Enum(TransportType), nullable=False)
    status: Mapped[ServerStatus] = mapped_column(Enum(ServerStatus), default=ServerStatus.ONLINE)
    permission_mode: Mapped[PermissionMode] = mapped_column(
        Enum(PermissionMode), default=PermissionMode.ALLOW_ALL
    )
    max_cost_usd_per_run: Mapped[float] = mapped_column(Float, default=0.50)
    max_steps_per_run: Mapped[int] = mapped_column(Integer, default=15)
    blocked_patterns: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # SHA-256 of the canonical tool manifest, pinned on first tools/list.
    tool_manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pinned_tools: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    traces: Mapped[list["AgentTrace"]] = relationship(
        "AgentTrace", back_populates="mcp_server", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MCPServer(id={self.id}, name={self.name})>"


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=settings.DEFAULT_ORG_ID,
        server_default=settings.DEFAULT_ORG_ID,
    )
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<APIKey(id={self.id}, name={self.name}, prefix={self.key_prefix})>"


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"trc_{uuid.uuid4().hex[:8]}")
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    environment: Mapped[str] = mapped_column(String(100), nullable=False)
    org_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=settings.DEFAULT_ORG_ID,
        server_default=settings.DEFAULT_ORG_ID,
        index=True,
    )
    status: Mapped[TraceStatus] = mapped_column(Enum(TraceStatus), default=TraceStatus.RUNNING)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    mcp_server_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("mcp_servers.id"), nullable=True
    )
    mcp_server: Mapped["MCPServer | None"] = relationship("MCPServer", back_populates="traces")
    spans: Mapped[list["TraceSpan"]] = relationship(
        "TraceSpan", back_populates="trace", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentTrace(id={self.id}, agent_name={self.agent_name}, status={self.status})>"


class TraceSpan(Base):
    __tablename__ = "trace_spans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"spn_{uuid.uuid4().hex[:8]}")
    trace_id: Mapped[str] = mapped_column(String, ForeignKey("agent_traces.id"), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String, nullable=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    span_type: Mapped[SpanType] = mapped_column(Enum(SpanType), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_or_server: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SpanStatus] = mapped_column(Enum(SpanStatus), default=SpanStatus.OK)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    guardrail_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Principal that initiated the span; used for separation-of-duties checks.
    requester_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    trace: Mapped["AgentTrace"] = relationship("AgentTrace", back_populates="spans")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TraceSpan(id={self.id}, trace_id={self.trace_id}, name={self.name})>"