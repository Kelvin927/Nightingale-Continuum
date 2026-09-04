from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.telemetry import (
    SafeTelemetrySink,
    TelemetryContractError,
    _validate_attributes,
    normalize_request_id,
    route_template,
)
from tests.conftest import auth


@dataclass
class Route:
    path: str


def test_request_identifiers_and_routes_never_export_untrusted_content() -> None:
    assert normalize_request_id("trace-2026:valid") == "trace-2026:valid"
    generated = normalize_request_id(None)
    assert len(generated) == 36
    sensitive = "patient@example.test +65 9123 4567"
    replacement = normalize_request_id(sensitive)
    assert replacement.startswith("sha256-") and len(replacement) == 55
    assert sensitive not in replacement

    assert route_template({"route": Route("/api/v1/patients/{patient_id}")}) == (
        "/api/v1/patients/{patient_id}"
    )
    assert route_template({}) == "__unmatched__"
    assert route_template({"route": Route("/patients/patient@example.test")}) == "__unmatched__"
    assert route_template({"route": object()}) == "__unmatched__"


def test_sink_is_bounded_returns_copies_and_rejects_non_allowlisted_data() -> None:
    with pytest.raises(ValueError, match="at least one"):
        SafeTelemetrySink(max_events=0)
    sink = SafeTelemetrySink(max_events=1)
    sink.emit(
        "http.request.completed",
        request_id="request-1",
        http_method="GET",
        route_template="/health",
        status_code=200,
        status_class="2xx",
        duration_ms=1.25,
    )
    sink.emit(
        "provider.call.completed",
        provider_name="local-provider",
        provider_status="live",
        failure_code=None,
        circuit_state="closed",
        duration_ms=2,
    )
    snapshot = sink.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0]["name"] == "provider.call.completed"
    snapshot[0]["attributes"]["provider_name"] = "changed"
    assert sink.snapshot()[0]["attributes"]["provider_name"] == "local-provider"

    with pytest.raises(TelemetryContractError, match="event name"):
        sink.emit("clinical.note.captured")
    with pytest.raises(TelemetryContractError, match="not allow-listed"):
        sink.emit("http.request.completed", transcript="Never export this")


@pytest.mark.parametrize(
    "attributes, message",
    [
        ({"request_id": "patient@example.test"}, "opaque"),
        ({"http_method": "TRACE"}, "http_method"),
        ({"route_template": "/patients/patient@example.test"}, "route_template"),
        ({"status_code": True}, "HTTP status"),
        ({"status_code": 700}, "HTTP status"),
        ({"status_class": "7xx"}, "status_class"),
        ({"duration_ms": True}, "duration_ms"),
        ({"duration_ms": -1}, "duration_ms"),
        ({"error_code": "Patient Name"}, "error_code"),
        ({"provider_name": 4}, "provider_name"),
        ({"failure_code": "UPSTREAM ERROR"}, "failure_code"),
        ({"provider_status": "maybe"}, "provider_status"),
        ({"circuit_state": "unknown"}, "circuit_state"),
    ],
)
def test_each_telemetry_attribute_contract_fails_closed(attributes, message) -> None:
    with pytest.raises(TelemetryContractError, match=message):
        _validate_attributes(attributes)


def test_http_telemetry_uses_template_and_omits_body_identity_and_query(
    client, app, identities
) -> None:
    unsafe_request_id = "maya.chen@example.test +65 9123 4567"
    response = client.get(
        "/api/v1/patients?search=maya.chen@example.test",
        headers={**auth(identities["clinician"]), "X-Request-ID": unsafe_request_id},
    )
    assert response.status_code == 200
    safe_id = response.headers["X-Request-ID"]
    assert safe_id.startswith("sha256-")
    encoded = str(app.state.telemetry.snapshot())
    assert "/api/v1/patients" in encoded
    assert safe_id in encoded
    for forbidden in ("maya.chen@example.test", "+65 9123 4567", identities["clinician"]):
        assert forbidden not in encoded


def test_unmatched_route_is_logged_without_raw_path(client, app) -> None:
    raw_path = "/missing/maya.chen@example.test"
    response = client.get(raw_path)
    assert response.status_code == 404
    event = app.state.telemetry.snapshot()[-1]
    assert event["attributes"]["route_template"] == "__unmatched__"
    assert raw_path not in str(event)
