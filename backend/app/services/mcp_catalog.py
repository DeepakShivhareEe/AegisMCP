"""MCP tool catalogs, manifest pinning and injection scanning.

Kept separate from :mod:`app.services.mcp_proxy` so the deterministic demo
catalog and the scanning helpers stay independently testable.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

# Descriptions and tool output are untrusted input that lands in the model's
# context, so both are scanned for hidden instructions.
_INJECTION_MARKERS: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all previous",
    "ignore the previous",
    "disregard previous",
    "disregard all previous",
    "override your instructions",
    "do not tell the user",
    "without telling the user",
    "<system>",
    "</system>",
    "<|im_start|>",
    "exfiltrate",
    "send the conversation",
    "send all messages",
    "reveal your system prompt",
    "curl http",
)
_LONG_BASE64 = re.compile(r"\b[A-Za-z0-9+/]{160,}={0,2}\b")

_DEMO_CATALOGS: dict[str, list[dict[str, Any]]] = {
    "postgres-prod-mcp": [
        {
            "name": "execute_query",
            "description": "Run a read-only SQL query against the analytics replica.",
            "inputSchema": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
        {
            "name": "list_tables",
            "description": "List tables in the public schema.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ],
    "github-repo-mcp": [
        {
            "name": "list_files",
            "description": "List files in a repository path.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
        {
            "name": "create_issue",
            "description": "Open a new issue on the configured repository.",
            "inputSchema": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                "required": ["title"],
            },
        },
    ],
    "filesystem-sandbox-mcp": [
        {
            "name": "read_file",
            "description": "Read a UTF-8 file inside the sandbox workspace.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write UTF-8 content inside the sandbox workspace.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    ],
    "stripe-billing-mcp": [
        {
            "name": "create_refund",
            "description": "Refund a charge in the connected Stripe account.",
            "inputSchema": {
                "type": "object",
                "properties": {"amount_cents": {"type": "integer"}},
                "required": ["amount_cents"],
            },
        },
        {
            "name": "get_balance",
            "description": "Read the current Stripe account balance.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ],
}


def register_demo_catalog(server_name: str, tools: list[dict[str, Any]]) -> None:
    """Replace a demo server's catalog (test seam for rug-pull scenarios)."""
    _DEMO_CATALOGS[server_name] = json.loads(json.dumps(tools))


def get_demo_catalog(server_name: str) -> list[dict[str, Any]]:
    """Return a copy of the demo catalog for a server."""
    return json.loads(json.dumps(_DEMO_CATALOGS.get(server_name, [])))


def demo_tool_output(server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Deterministic tool execution result for an offline demo server."""
    if tool_name == "execute_query":
        return {"rows": [{"quarter": "Q4", "revenue": 1284000}], "row_count": 1}
    if tool_name == "list_tables":
        return {"tables": ["customers", "orders", "sales"]}
    if tool_name == "list_files":
        return {"files": ["README.md", "src/main.py"], "path": arguments.get("path", "/")}
    if tool_name == "create_issue":
        return {"number": 482, "url": "https://github.com/example/repo/issues/482"}
    if tool_name == "read_file":
        # Deliberately contains a secret and PII so output screening is provable.
        return {
            "path": arguments.get("path", ""),
            "content": (
                "Quarterly report\n"
                "Owner: jane.doe@example.com\n"
                "Stripe key: sk_live_51H8xQ2eZvKYlo2C9q3demo\n"
            ),
        }
    if tool_name == "write_file":
        return {"bytes_written": len(str(arguments.get("content", "")))}
    if tool_name == "create_refund":
        return {
            "refund_id": "re_3Pdemo",
            "amount_cents": arguments.get("amount_cents", 0),
            "status": "succeeded",
        }
    if tool_name == "get_balance":
        return {"available": [{"amount": 4200, "currency": "usd"}]}
    return {"echo": {"server": server_name, "tool": tool_name, "arguments": arguments}}


def canonical_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise a catalog into the deterministic pinned shape."""
    canonical: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        canonical.append(
            {
                "name": str(tool.get("name") or ""),
                "description": str(tool.get("description") or ""),
                "inputSchema": tool.get("inputSchema") or {},
            }
        )
    canonical.sort(key=lambda item: (item["name"], item["description"]))
    return canonical


def manifest_hash(canonical: list[dict[str, Any]]) -> str:
    """Deterministic SHA-256 over the canonical tool manifest."""
    serialised = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def scan_tool_descriptions(canonical: list[dict[str, Any]]) -> list[str]:
    """Return OWASP MCP03 findings for hidden instructions in tool metadata."""
    findings: list[str] = []
    for tool in canonical:
        haystack = f"{tool['name']}\n{tool['description']}".lower()
        for marker in _INJECTION_MARKERS:
            if marker in haystack:
                findings.append(f"{tool['name']}: contains '{marker}'")
        if _LONG_BASE64.search(tool["description"]):
            findings.append(f"{tool['name']}: contains a long encoded payload")
    return findings


def scan_tool_output(text: str) -> list[str]:
    """Detect indirect prompt injection before output reaches the model."""
    lowered = text.lower()
    markers = [marker for marker in _INJECTION_MARKERS if marker in lowered]
    if _LONG_BASE64.search(text):
        markers.append("long encoded payload")
    return markers


def is_demo_server(endpoint_url: str) -> bool:
    """Demo servers are served by the in-process catalog instead of HTTP."""
    url = (endpoint_url or "").strip()
    if url.startswith("demo://"):
        return True
    host = urlsplit(url).hostname or ""
    return host.endswith(".internal") or host.endswith(".test")
