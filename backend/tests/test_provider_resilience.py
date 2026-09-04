from __future__ import annotations

import time

import pytest

from app.providers import (
    ProviderCallError,
    ProviderGateway,
    ProviderUnavailable,
    RedactedPayload,
    ScribeDraft,
)
from app.scribe import LocalDeterministicScribe
from app.telemetry import SafeTelemetrySink


def payload(*, passed: bool = True) -> RedactedPayload:
    return RedactedPayload(
        text="The redacted medication dose is 20 mg.",
        sanitized_sha256="abc123",
        detector_version="test-redactor",
        clinical_anchor_count=2,
        receipt_passed=passed,
        purpose="doctor_consult",
    )


class SlowProvider:
    name = "slow-provider"

    def generate(self, *, payload: RedactedPayload, interaction_type: str) -> ScribeDraft:
        del payload, interaction_type
        time.sleep(0.03)
        return ScribeDraft("Late", "Late result", 0.5, ())


class UnavailableProvider:
    name = "unavailable-provider"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, payload: RedactedPayload, interaction_type: str) -> ScribeDraft:
        del payload, interaction_type
        self.calls += 1
        raise ProviderUnavailable


class UnexpectedProvider:
    name = "unexpected-provider"

    def generate(self, *, payload: RedactedPayload, interaction_type: str) -> ScribeDraft:
        del payload, interaction_type
        raise RuntimeError("raw provider detail that must not cross the boundary")


class RecoveringProvider:
    name = "recovering-provider"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, payload: RedactedPayload, interaction_type: str) -> ScribeDraft:
        del payload, interaction_type
        self.calls += 1
        if self.calls == 1:
            raise ProviderUnavailable
        return ScribeDraft("Recovered", "Recovered result", 0.8, ())


def test_gateway_requires_positive_limits_and_passing_receipt() -> None:
    provider = LocalDeterministicScribe()
    with pytest.raises(ValueError, match="positive"):
        ProviderGateway(provider, timeout_seconds=0)
    with pytest.raises(ValueError, match="positive"):
        ProviderGateway(provider, failure_threshold=0)
    with pytest.raises(ValueError, match="positive"):
        ProviderGateway(provider, reset_after_seconds=0)
    gateway = ProviderGateway(provider)
    try:
        with pytest.raises(ValueError, match="passing redaction"):
            gateway.generate(payload=payload(passed=False), interaction_type="doctor_consult")
    finally:
        gateway.close()
    assert provider.last_received_text is None


def test_gateway_returns_live_typed_result_and_resets_state() -> None:
    provider = LocalDeterministicScribe()
    gateway = ProviderGateway(provider)
    try:
        outcome = gateway.generate(payload=payload(), interaction_type="doctor_consult")
        assert outcome.status == "live"
        assert outcome.failure_code is None
        assert outcome.provider_name == provider.name
        assert gateway.state == "closed"
        assert provider.last_received_text == payload().text
    finally:
        gateway.close()


def test_deadline_uses_rule_only_fallback_and_never_returns_late_result() -> None:
    fallback = LocalDeterministicScribe()
    gateway = ProviderGateway(SlowProvider(), fallback=fallback, timeout_seconds=0.001)
    try:
        outcome = gateway.generate(payload=payload(), interaction_type="doctor_consult")
        assert outcome.status == "rule_only_degraded"
        assert outcome.failure_code == "provider_deadline_exceeded"
        assert "provider_deadline_exceeded" in outcome.draft.flags
        assert "rule_only_degraded" in outcome.draft.flags
        assert outcome.provider_name == fallback.name
    finally:
        gateway.close()


def test_failures_open_circuit_without_recalling_primary() -> None:
    primary = UnavailableProvider()
    fallback = LocalDeterministicScribe()
    gateway = ProviderGateway(
        primary,
        fallback=fallback,
        failure_threshold=2,
        reset_after_seconds=60,
    )
    try:
        first = gateway.generate(payload=payload(), interaction_type="doctor_consult")
        second = gateway.generate(payload=payload(), interaction_type="doctor_consult")
        third = gateway.generate(payload=payload(), interaction_type="doctor_consult")
        assert first.failure_code == second.failure_code == "provider_unavailable"
        assert third.failure_code == "provider_circuit_open"
        assert primary.calls == 2
        assert gateway.state == "open"
    finally:
        gateway.close()


def test_half_open_call_recovers_and_closes_circuit() -> None:
    now = [100.0]
    primary = RecoveringProvider()
    fallback = LocalDeterministicScribe()
    gateway = ProviderGateway(
        primary,
        fallback=fallback,
        failure_threshold=1,
        reset_after_seconds=5,
        clock=lambda: now[0],
    )
    try:
        failed = gateway.generate(payload=payload(), interaction_type="doctor_consult")
        assert failed.failure_code == "provider_unavailable"
        assert gateway.state == "open"
        now[0] = 106.0
        assert gateway.state == "half_open"
        recovered = gateway.generate(payload=payload(), interaction_type="doctor_consult")
        assert recovered.status == "live"
        assert recovered.draft.title == "Recovered"
        assert gateway.state == "closed"
    finally:
        gateway.close()


def test_unexpected_exception_is_stable_and_missing_fallback_fails_closed() -> None:
    fallback = LocalDeterministicScribe()
    gateway = ProviderGateway(UnexpectedProvider(), fallback=fallback)
    try:
        outcome = gateway.generate(payload=payload(), interaction_type="doctor_consult")
        assert outcome.failure_code == "provider_unavailable"
    finally:
        gateway.close()

    no_fallback = ProviderGateway(UnavailableProvider())
    try:
        with pytest.raises(ProviderCallError, match="provider_unavailable"):
            no_fallback.generate(payload=payload(), interaction_type="doctor_consult")
    finally:
        no_fallback.close()


def test_provider_telemetry_reports_state_without_exporting_payload() -> None:
    telemetry = SafeTelemetrySink()
    primary = UnavailableProvider()
    gateway = ProviderGateway(
        primary,
        fallback=LocalDeterministicScribe(),
        failure_threshold=1,
        telemetry=telemetry,
    )
    try:
        outcome = gateway.generate(payload=payload(), interaction_type="doctor_consult")
        assert outcome.status == "rule_only_degraded"
    finally:
        gateway.close()
    event = telemetry.snapshot()[-1]
    assert event["attributes"] == {
        "provider_name": primary.name,
        "provider_status": "rule_only_degraded",
        "failure_code": "provider_unavailable",
        "circuit_state": "open",
        "duration_ms": event["attributes"]["duration_ms"],
    }
    assert payload().text not in str(event)

    failed_closed = ProviderGateway(UnavailableProvider(), telemetry=telemetry)
    try:
        with pytest.raises(ProviderCallError):
            failed_closed.generate(payload=payload(), interaction_type="doctor_consult")
    finally:
        failed_closed.close()
    assert telemetry.snapshot()[-1]["attributes"]["provider_status"] == "failed_closed"
