"""
AegisMCP Python SDK - Real-time AI Agent Runtime Gateway Client

Enforcement model
-----------------
Guardrails are evaluated BEFORE guarded code runs. ``guard_tool`` and
``intercept(..., input_payload=...)`` send the tool input to the gateway,
which either allows the call, blocks it, or pauses it for human approval.
A blocked call raises ``AegisGuardrailBlockedError`` without ever executing the
tool body; a HITL call blocks until an operator decides, then either runs or
raises ``AegisHITLRejectedError``.

After the body finishes, the span is completed with its output, latency, token
and cost data (``POST /api/v1/spans/{span_id}/complete``).

Usage:
    from aegis_sdk import AegisClient

    client = AegisClient(api_key="aegis_live_...", base_url="http://localhost:8000")

    @client.guard_tool("postgres-prod-mcp", "execute_query")
    def run_query(sql: str):
        return db.execute(sql)

    with client.intercept(
        "stripe-billing-mcp", "create_refund", input_payload={"amount": 45000}
    ) as ctx:
        result = stripe.Refund.create(amount=45000)
        ctx.set_output({"refund_id": result.id})
"""

import time
import uuid
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, Generator, Optional
from urllib.parse import urljoin

import httpx

_MAX_PAYLOAD_DEPTH = 4
_MAX_ITEMS = 50
_MAX_STRING = 2000


class AegisError(Exception):
    """Base exception for AegisMCP SDK errors."""


class AegisGuardrailBlockedError(AegisError):
    """Raised when a tool call is blocked by guardrails before execution."""

    def __init__(self, reason: str, trace_id: str, span_id: str):
        self.reason = reason
        self.trace_id = trace_id
        self.span_id = span_id
        super().__init__(f"Guardrail blocked: {reason} (trace={trace_id}, span={span_id})")


class AegisHITLRejectedError(AegisError):
    """Raised when a HITL request is rejected by a human operator."""

    def __init__(self, reason: str, trace_id: str, span_id: str):
        self.reason = reason
        self.trace_id = trace_id
        self.span_id = span_id
        super().__init__(f"HITL rejected: {reason} (trace={trace_id}, span={span_id})")


class AegisConnectionError(AegisError):
    """Raised when connection to the AegisMCP gateway fails."""


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_STRING else text[:_MAX_STRING] + "...(truncated)"


def _jsonable(value: Any, depth: int = 0) -> Any:
    """Convert arbitrary Python values into JSON-serialisable data.

    Agent inputs and tool results routinely contain dataclasses, ORM rows or
    SDK objects. Sending them raw makes ``json.dumps`` explode inside httpx, so
    every payload is normalised here instead of failing at request time.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= _MAX_PAYLOAD_DEPTH:
        return _truncate(repr(value))
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item, depth + 1)
            for key, item in list(value.items())[:_MAX_ITEMS]
        }
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item, depth + 1) for item in list(value)[:_MAX_ITEMS]]
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _jsonable(vars(value), depth + 1)
    return _truncate(repr(value))


@dataclass
class InterceptContext:
    """Context for one guarded tool call."""

    trace_id: str
    span_id: str
    server_name: str
    tool_name: str
    step_index: int = 0
    input_payload: Dict[str, Any] = field(default_factory=dict)
    output_payload: Optional[Dict[str, Any]] = None
    latency_ms: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    status: str = "OK"
    completion_error: Optional[str] = None
    _started_at: float = field(default_factory=time.perf_counter)

    def set_input(self, payload: Dict[str, Any]) -> None:
        self.input_payload = _jsonable(payload) if payload else {}

    def set_output(self, payload: Any) -> None:
        self.output_payload = _jsonable(payload)

    def set_latency(self, ms: int) -> None:
        self.latency_ms = max(0, int(ms))

    def set_tokens(self, tokens: int) -> None:
        self.tokens_used = max(0, int(tokens))

    def set_cost(self, cost: float) -> None:
        self.cost_usd = max(0.0, float(cost))

    @property
    def elapsed_ms(self) -> int:
        return max(0, int((time.perf_counter() - self._started_at) * 1000))


class AegisClient:
    """
    AegisMCP Runtime Gateway Client.

    Intercepts real agent tool calls and LLM spans, evaluates guardrails
    in real time, and enforces policies (block, HITL, allow) before the
    guarded code executes.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
        hitl_poll_interval: float = 1.5,
        hitl_timeout: float = 300.0,
        agent_name: str = "sdk-agent",
        environment: str = "production",
    ):
        """
        Initialize the AegisMCP client.

        Args:
            api_key: API key from the AegisMCP dashboard (aegis_live_...)
            base_url: Base URL of the AegisMCP gateway
            timeout: HTTP request timeout in seconds
            hitl_poll_interval: How often to poll for a HITL decision (seconds)
            hitl_timeout: Maximum time to wait for a HITL decision (seconds)
            agent_name: Agent identity recorded on traces
            environment: Environment label recorded on traces
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.hitl_poll_interval = hitl_poll_interval
        self.hitl_timeout = hitl_timeout
        self.agent_name = agent_name
        self.environment = environment
        self._client = httpx.Client(timeout=timeout)
        self._trace_id: Optional[str] = None
        self._step_index = 0

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Aegis-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        try:
            response = self._client.request(method, url, headers=self._headers(), **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            try:
                error_data = exc.response.json()
                detail = error_data.get("detail", str(error_data))
            except Exception:  # noqa: BLE001 - error body may not be JSON
                detail = exc.response.text
            raise AegisError(f"HTTP {exc.response.status_code}: {detail}") from exc
        except httpx.RequestError as exc:
            raise AegisConnectionError(f"Failed to connect to {self.base_url}: {exc}") from exc

    def _new_trace_id(self) -> str:
        return f"trc_{uuid.uuid4().hex[:8]}"

    def _next_step_index(self) -> int:
        """Return the next monotonic step index for this trace."""
        index = self._step_index
        self._step_index += 1
        return index

    def _send_intercept(
        self,
        server_name: str,
        tool_name: str,
        span_type: str,
        context: InterceptContext,
    ) -> Dict[str, Any]:
        """Ask the gateway for a verdict before the tool body executes."""
        payload = {
            "agent_name": self.agent_name,
            "environment": self.environment,
            "span_type": span_type,
            "name": tool_name,
            "model_or_server": server_name,
            "parent_span_id": None,
            "step_index": context.step_index,
            "latency_ms": context.latency_ms,
            "tokens_used": context.tokens_used,
            "cost_usd": context.cost_usd,
            "input_payload": context.input_payload,
            "output_payload": None,
            "trace_id": context.trace_id,
        }
        response = self._request("POST", "/api/v1/proxy/intercept", json=payload)
        return response.json()

    def _poll_span_status(self, span_id: str) -> Dict[str, Any]:
        """Block until an operator approves or rejects a pending span."""
        started = time.time()
        while time.time() - started < self.hitl_timeout:
            response = self._request("GET", f"/api/v1/spans/{span_id}/status")
            data = response.json()
            if data.get("status") in ("OK", "BLOCKED", "ERROR"):
                return data
            time.sleep(self.hitl_poll_interval)
        raise AegisError(f"HITL timeout after {self.hitl_timeout}s for span {span_id}")

    def _authorize(
        self,
        server_name: str,
        tool_name: str,
        span_type: str,
        context: InterceptContext,
    ) -> None:
        """Evaluate policy and wait for HITL. Raises before the body runs."""
        response = self._send_intercept(server_name, tool_name, span_type, context)

        status = response.get("status") or "OK"
        reason = response.get("reason")
        context.span_id = response.get("span_id") or context.span_id
        context.trace_id = response.get("trace_id") or context.trace_id
        context.status = status

        if status in ("BLOCKED", "LOOP_KILLED"):
            raise AegisGuardrailBlockedError(
                reason or "Blocked by guardrails", context.trace_id, context.span_id
            )
        if status == "REJECTED":
            raise AegisHITLRejectedError(
                reason or "Rejected by operator", context.trace_id, context.span_id
            )
        if status != "PENDING_APPROVAL":
            return

        polled = self._poll_span_status(context.span_id)
        poll_status = polled.get("status")
        if poll_status == "OK":
            context.status = "OK"
            return
        raise AegisHITLRejectedError(
            polled.get("guardrail_reason") or reason or "Rejected by operator",
            context.trace_id,
            context.span_id,
        )

    def _complete_span(self, context: InterceptContext) -> None:
        """Report post-execution output and usage; never mask the tool result."""
        if not context.span_id:
            return
        payload = {
            "output_payload": context.output_payload,
            "latency_ms": context.latency_ms or context.elapsed_ms,
            "tokens_used": context.tokens_used,
            "cost_usd": context.cost_usd,
        }
        try:
            self._request(
                "POST", f"/api/v1/spans/{context.span_id}/complete", json=payload
            )
        except AegisError as exc:
            context.completion_error = str(exc)
            warnings.warn(
                f"AegisMCP span completion failed: {exc}", RuntimeWarning, stacklevel=3
            )

    @contextmanager
    def intercept(
        self,
        server_name: str,
        tool_name: str,
        span_type: str = "MCP_TOOL_CALL",
        input_payload: Optional[Dict[str, Any]] = None,
    ) -> Generator[InterceptContext, None, None]:
        """
        Context manager that authorises a tool call before it executes.

        ``input_payload`` supplies the tool arguments to the guardrail engine.
        The call is always authorised *before* the body executes, so a blocked
        call never triggers local side effects.

        Usage:
            with client.intercept(
                "stripe-billing-mcp", "create_refund", input_payload={"amount": 45000}
            ) as ctx:
                result = stripe.Refund.create(amount=45000)
                ctx.set_output({"refund_id": result.id})
        """
        context = InterceptContext(
            trace_id=self._trace_id or self._new_trace_id(),
            span_id="",
            server_name=server_name,
            tool_name=tool_name,
            step_index=self._next_step_index(),
        )
        self._trace_id = context.trace_id
        context.set_input(input_payload or {})

        authorized = False
        body_started = time.perf_counter()
        try:
            # Pre-execution enforcement: this raises before the body runs when
            # the call is blocked, loop-killed or rejected by an operator.
            self._authorize(server_name, tool_name, span_type, context)
            authorized = True
            # Measure the tool body only: HITL waiting time is not latency.
            body_started = time.perf_counter()
            yield context
        finally:
            context.set_latency(int((time.perf_counter() - body_started) * 1000))
            if authorized:
                self._complete_span(context)

    @staticmethod
    def _build_input_payload(args: tuple, kwargs: dict) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if args:
            payload["args"] = _jsonable(list(args))
        if kwargs:
            payload["kwargs"] = _jsonable(kwargs)
        return payload

    def guard_tool(
        self,
        server_name: str,
        tool_name: str,
        span_type: str = "MCP_TOOL_CALL",
    ) -> Callable:
        """Decorator that authorises a tool call before running it.

        Usage:
            @client.guard_tool("postgres-prod-mcp", "execute_query")
            def run_query(sql: str):
                return db.execute(sql)
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                payload = self._build_input_payload(args, kwargs)
                with self.intercept(
                    server_name, tool_name, span_type, input_payload=payload
                ) as ctx:
                    result = func(*args, **kwargs)
                    if result is not None:
                        if isinstance(result, dict):
                            ctx.set_output(result)
                        else:
                            ctx.set_output({"result": _jsonable(result)})
                    return result
            return wrapper
        return decorator

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "AegisClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def create_client(api_key: str, base_url: str = "http://localhost:8000") -> AegisClient:
    """Create an AegisClient instance."""
    return AegisClient(api_key=api_key, base_url=base_url)
