"""Shared SSE broadcaster instance.

A single module-level instance is imported by the API routes and by the MCP/OTLP
services so every ingestion path broadcasts to the same subscriber set.
"""

from app.services.sse_manager import SSEManager

sse_manager = SSEManager()
