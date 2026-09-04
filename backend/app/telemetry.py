"""Emit bounded, low-cardinality operational telemetry without clinical content."""

from __future__ import annotations

import re
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from threading import Lock
from typing import Any
from uuid import uuid4

SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z")
SAFE_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")
SAFE_ROUTE = re.compile(r"/[A-Za-z0-9_{}./:-]{0,159}\Z")

ALLOWED_EVENT_NAMES = {
    "http.request.completed",
    "http.request.failed",
    "provider.call.completed",
}
ALLOWED_ATTRIBUTE_KEYS = {
    "request_id",
    "http_method",
    "route_template",
    "status_code",
    "status_class",
    "duration_ms",
    "error_code",
    "provider_name",
    "provider_status",
    "failure_code",
    "circuit_state",
}
ALLOWED_HTTP_METHODS = {"DELETE", "GET", "OPTIONS", "PATCH", "POST", "PUT"}
ALLOWED_STATUS_CLASSES = {"2xx", "3xx", "4xx", "5xx"}
ALLOWED_PROVIDER_STATUSES = {"live", "rule_only_degraded", "failed_closed"}
ALLOWED_CIRCUIT_STATES = {"closed", "open", "half_open"}


class TelemetryContractError(ValueError):
    """Raised when code attempts to export a non-approved telemetry field."""


def normalize_request_id(candidate: str | None) -> str:
    """Keep a valid opaque ID or irreversibly replace untrusted content with a digest."""

    if candidate and SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    if candidate:
        digest = sha256(candidate.encode("utf-8")).hexdigest()[:48]
        return f"sha256-{digest}"
    return str(uuid4())


def route_template(scope: dict[str, Any]) -> str:
    """Return the registered route pattern, never the identifier-bearing request path."""

    route = scope.get("route")
    candidate = getattr(route, "path", None)
    if isinstance(candidate, str) and SAFE_ROUTE.fullmatch(candidate):
        return candidate
    return "__unmatched__"


@dataclass(frozen=True)
class SafeTelemetryEvent:
    name: str
    occurred_at: str
    attributes: dict[str, str | int | float | None]


def _validate_attributes(attributes: dict[str, Any]) -> None:
    unexpected = set(attributes) - ALLOWED_ATTRIBUTE_KEYS
    if unexpected:
        raise TelemetryContractError(f"Telemetry fields are not allow-listed: {sorted(unexpected)}")

    request_id = attributes.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or not SAFE_REQUEST_ID.fullmatch(request_id)
    ):
        raise TelemetryContractError("request_id must be an opaque identifier")
    method = attributes.get("http_method")
    if method is not None and method not in ALLOWED_HTTP_METHODS:
        raise TelemetryContractError("http_method is not allow-listed")
    route = attributes.get("route_template")
    if (
        route is not None
        and route != "__unmatched__"
        and (not isinstance(route, str) or not SAFE_ROUTE.fullmatch(route))
    ):
        raise TelemetryContractError("route_template must be a registered path pattern")
    status_code = attributes.get("status_code")
    if status_code is not None and (
        not isinstance(status_code, int)
        or isinstance(status_code, bool)
        or not 100 <= status_code <= 599
    ):
        raise TelemetryContractError("status_code must be an HTTP status")
    status_class = attributes.get("status_class")
    if status_class is not None and status_class not in ALLOWED_STATUS_CLASSES:
        raise TelemetryContractError("status_class is not allow-listed")
    duration_ms = attributes.get("duration_ms")
    if duration_ms is not None and (
        not isinstance(duration_ms, (int, float))
        or isinstance(duration_ms, bool)
        or not 0 <= duration_ms <= 3_600_000
    ):
        raise TelemetryContractError("duration_ms is outside the operational bound")
    for key in ("error_code", "provider_name", "failure_code"):
        value = attributes.get(key)
        if value is not None and (not isinstance(value, str) or not SAFE_TOKEN.fullmatch(value)):
            raise TelemetryContractError(f"{key} must be a low-cardinality token")
    provider_status = attributes.get("provider_status")
    if provider_status is not None and provider_status not in ALLOWED_PROVIDER_STATUSES:
        raise TelemetryContractError("provider_status is not allow-listed")
    circuit_state = attributes.get("circuit_state")
    if circuit_state is not None and circuit_state not in ALLOWED_CIRCUIT_STATES:
        raise TelemetryContractError("circuit_state is not allow-listed")


class SafeTelemetrySink:
    """A thread-safe development sink with explicit retention and export contracts."""

    def __init__(self, *, max_events: int = 1000) -> None:
        if max_events < 1:
            raise ValueError("Telemetry retention must keep at least one event")
        self.max_events = max_events
        self._events: deque[SafeTelemetryEvent] = deque(maxlen=max_events)
        self._lock = Lock()

    def emit(self, name: str, **attributes: str | int | float | None) -> None:
        if name not in ALLOWED_EVENT_NAMES:
            raise TelemetryContractError("Telemetry event name is not allow-listed")
        _validate_attributes(attributes)
        event = SafeTelemetryEvent(
            name=name,
            occurred_at=datetime.now(UTC).isoformat(),
            attributes=dict(attributes),
        )
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy([asdict(event) for event in self._events])
