"""Deterministic PII and secret redaction.

Every payload that is persisted (spans, traces) or broadcast over SSE passes
through :func:`redact_payload` first, so a leaked prompt, tool argument or tool
result never becomes durable storage. Redaction is deterministic and
idempotent: running it twice yields the same output because the replacement
tokens contain no matchable pattern.

Secrets are matched by well-known token shapes (Stripe, OpenAI, GitHub, AWS,
JWTs, bearer headers) and by sensitive object keys. PII is matched by shape
(SSN, payment card with a Luhn check, email address).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SECRET = "[REDACTED:SECRET]"
JWT = "[REDACTED:JWT]"
SSN = "[REDACTED:SSN]"
CARD = "[REDACTED:CARD]"
EMAIL = "[REDACTED:EMAIL]"

_MAX_DEPTH = 6
_MAX_ITEMS = 200
_MAX_STRING = 20_000

_SENSITIVE_KEY_TOKENS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "private_key",
    "client_secret",
    "card_number",
    "cvv",
    "ssn",
    "session",
)

# Order matters: the JWT pattern must run before the generic bearer pattern.
_TEXT_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("secret", re.compile(r"\bsk_live_[A-Za-z0-9]{8,}\b"), SECRET),
    ("secret", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), SECRET),
    ("secret", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"), SECRET),
    ("secret", re.compile(r"\bAKIA[0-9A-Z]{12,}\b"), SECRET),
    ("secret", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), SECRET),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b"),
        JWT,
    ),
    ("secret", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{12,}=*"), f"Bearer {SECRET}"),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), SSN),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        EMAIL,
    ),
)

_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


@dataclass
class RedactionReport:
    """Counts of redactions by category."""

    counts: dict[str, int] = field(default_factory=dict)

    def add(self, category: str, amount: int = 1) -> None:
        if amount <= 0:
            return
        self.counts[category] = self.counts.get(category, 0) + amount

    def extend(self, other: "RedactionReport") -> None:
        for category, amount in other.counts.items():
            self.add(category, amount)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted(self.counts))

    def summary(self) -> str | None:
        if not self.counts:
            return None
        detail = ", ".join(f"{name}={self.counts[name]}" for name in self.categories)
        return f"Redacted sensitive data ({detail})"


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - 48
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _redact_card(match: re.Match[str], report: RedactionReport) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if len(digits) < 13 or len(digits) > 19 or not _luhn_valid(digits):
        return match.group(0)
    report.add("card")
    return CARD


def redact_text(text: str, report: RedactionReport | None = None) -> str:
    """Mask secrets and PII inside a string."""
    report = report if report is not None else RedactionReport()
    if not text:
        return text
    if len(text) > _MAX_STRING:
        text = text[:_MAX_STRING] + "...(truncated)"

    redacted = text
    for category, pattern, replacement in _TEXT_RULES:
        redacted, hits = pattern.subn(replacement, redacted)
        report.add(category, hits)

    redacted = _CARD_CANDIDATE.sub(lambda match: _redact_card(match, report), redacted)
    return redacted


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _SENSITIVE_KEY_TOKENS)


def _redact_value(value: Any, report: RedactionReport, depth: int) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value, report)
    if isinstance(value, bytes):
        return SECRET
    if depth >= _MAX_DEPTH:
        return redact_text(str(value), report)

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_ITEMS:
                result["..."] = f"{len(value) - _MAX_ITEMS} more keys"
                break
            key_text = str(key)
            if _is_sensitive_key(key_text) and item not in (None, "", [], {}):
                report.add("secret_key")
                result[key_text] = SECRET
            else:
                result[key_text] = _redact_value(item, report, depth + 1)
        return result

    if isinstance(value, (list, tuple, set)):
        items = list(value)
        redacted_items = [
            _redact_value(item, report, depth + 1) for item in items[:_MAX_ITEMS]
        ]
        if len(items) > _MAX_ITEMS:
            redacted_items.append(f"...({len(items) - _MAX_ITEMS} more items)")
        return redacted_items

    return redact_text(str(value), report)


def redact_payload(
    payload: Any, report: RedactionReport | None = None
) -> tuple[Any, RedactionReport]:
    """Return a redacted deep copy of ``payload`` plus a redaction report."""
    report = report if report is not None else RedactionReport()
    return _redact_value(payload, report, 0), report


def redact_mapping(
    payload: dict[str, Any] | None, report: RedactionReport | None = None
) -> tuple[dict[str, Any] | None, RedactionReport]:
    """Redact a span payload while preserving the ``dict | None`` shape."""
    if payload is None:
        return None, report if report is not None else RedactionReport()
    redacted, active_report = redact_payload(payload, report)
    if not isinstance(redacted, dict):  # pragma: no cover - defensive
        redacted = {"value": redacted}
    return redacted, active_report
