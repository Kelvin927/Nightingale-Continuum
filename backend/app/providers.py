"""Enforce typed, deadline-bounded calls across the external AI boundary."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Protocol

from .telemetry import SafeTelemetrySink


@dataclass(frozen=True)
class RedactedPayload:
    """Text that has passed both privacy removal and clinical-anchor fidelity checks."""

    text: str
    sanitized_sha256: str
    detector_version: str
    clinical_anchor_count: int
    receipt_passed: bool
    purpose: str


@dataclass(frozen=True)
class ScribeDraft:
    title: str
    content: str
    confidence: float
    flags: tuple[str, ...]


class ScribeProvider(Protocol):
    name: str

    def generate(self, *, payload: RedactedPayload, interaction_type: str) -> ScribeDraft: ...


class ProviderCallError(RuntimeError):
    """Stable provider failure that is safe to expose as a machine-readable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProviderDeadlineExceeded(ProviderCallError):
    def __init__(self) -> None:
        super().__init__("provider_deadline_exceeded")


class ProviderUnavailable(ProviderCallError):
    def __init__(self) -> None:
        super().__init__("provider_unavailable")


class ProviderCircuitOpen(ProviderCallError):
    def __init__(self) -> None:
        super().__init__("provider_circuit_open")


@dataclass(frozen=True)
class ProviderOutcome:
    draft: ScribeDraft
    provider_name: str
    status: str
    failure_code: str | None


class ProviderGateway:
    """Bound provider latency and expose an explicit deterministic fallback state."""

    def __init__(
        self,
        provider: ScribeProvider,
        *,
        fallback: ScribeProvider | None = None,
        timeout_seconds: float = 2.0,
        failure_threshold: int = 3,
        reset_after_seconds: float = 30.0,
        clock: Callable[[], float] = monotonic,
        telemetry: SafeTelemetrySink | None = None,
    ) -> None:
        if timeout_seconds <= 0 or failure_threshold < 1 or reset_after_seconds <= 0:
            raise ValueError("Provider resilience limits must be positive")
        self.provider = provider
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.failure_threshold = failure_threshold
        self.reset_after_seconds = reset_after_seconds
        self._clock = clock
        self._telemetry = telemetry
        self._failure_count = 0
        self._opened_until: float | None = None
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="scribe-provider")

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_until is None:
                return "closed"
            if self._clock() < self._opened_until:
                return "open"
            return "half_open"

    def _before_call(self) -> None:
        with self._lock:
            if self._opened_until is None:
                return
            if self._clock() < self._opened_until:
                raise ProviderCircuitOpen
            self._opened_until = None
            self._failure_count = 0

    def _record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._opened_until = None

    def _record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._opened_until = self._clock() + self.reset_after_seconds

    def _invoke(self, payload: RedactedPayload, interaction_type: str) -> ScribeDraft:
        future = self._executor.submit(
            self.provider.generate,
            payload=payload,
            interaction_type=interaction_type,
        )
        try:
            return future.result(timeout=self.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise ProviderDeadlineExceeded from exc
        except ProviderCallError:
            raise
        except Exception as exc:
            raise ProviderUnavailable from exc

    def _fallback(
        self, payload: RedactedPayload, interaction_type: str, code: str
    ) -> ProviderOutcome:
        if self.fallback is None:
            raise ProviderCallError(code)
        draft = self.fallback.generate(payload=payload, interaction_type=interaction_type)
        flags = tuple(dict.fromkeys((*draft.flags, "rule_only_degraded", code)))
        degraded = ScribeDraft(draft.title, draft.content, draft.confidence, flags)
        return ProviderOutcome(degraded, self.fallback.name, "rule_only_degraded", code)

    def _emit(self, outcome: ProviderOutcome, started: float) -> None:
        if self._telemetry is None:
            return
        self._telemetry.emit(
            "provider.call.completed",
            provider_name=self.provider.name,
            provider_status=outcome.status,
            failure_code=outcome.failure_code,
            circuit_state=self.state,
            duration_ms=round(max(0.0, self._clock() - started) * 1000, 3),
        )

    def generate(self, *, payload: RedactedPayload, interaction_type: str) -> ProviderOutcome:
        if not payload.receipt_passed:
            raise ValueError("Provider gateway requires a passing redaction receipt")
        started = self._clock()
        try:
            self._before_call()
            draft = self._invoke(payload, interaction_type)
        except ProviderCallError as exc:
            if exc.code != "provider_circuit_open":
                self._record_failure()
            try:
                outcome = self._fallback(payload, interaction_type, exc.code)
            except ProviderCallError:
                self._emit(
                    ProviderOutcome(
                        ScribeDraft("", "", 0.0, ()),
                        self.provider.name,
                        "failed_closed",
                        exc.code,
                    ),
                    started,
                )
                raise
            self._emit(outcome, started)
            return outcome
        self._record_success()
        outcome = ProviderOutcome(draft, self.provider.name, "live", None)
        self._emit(outcome, started)
        return outcome

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
