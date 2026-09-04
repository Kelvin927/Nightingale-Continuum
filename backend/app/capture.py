"""Model a provider-neutral streaming transcript and provisional safety lane."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import append_audit
from .configuration import active_configuration
from .models import (
    CaptureSession,
    Entry,
    Patient,
    SafetySignal,
    TranscriptSegment,
    User,
)
from .providers import ProviderGateway
from .schemas import StreamSegmentRequest
from .scribe import ingest_scribe

STREAM_CONTRACT_VERSION = "2026-09-01"
PROVIDER_LANGUAGE_TAGS = frozenset({"en", "en-sg", "ms", "ms-sg", "zh", "zh-sg"})
PROVIDER_LANGUAGE_BASES = frozenset({"en", "ms", "zh"})
ALLERGY_PATTERN = re.compile(
    r"\b(?:allergic(?:\s+reaction)?\s+to|allergy\s+to)\s+"
    r"(?P<substance>[a-z][a-z-]{2,30})\b",
    re.IGNORECASE,
)
MEDICATION_DOSE_PATTERN = re.compile(
    r"\b(?P<drug>lisinopril|metformin|amlodipine|amoxicillin|penicillin|aspirin|ibuprofen)"
    r"\s+(?P<dose>\d+(?:\.\d+)?)\s*(?P<unit>mg|mcg|g|ml)\b",
    re.IGNORECASE,
)
NEGATION_PATTERN = re.compile(r"\b(?:not|never|no)\s+$", re.IGNORECASE)


class CaptureContractError(ValueError):
    """Represent a stable, user-correctable streaming contract failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SegmentResult:
    segment: TranscriptSegment
    signals: tuple[SafetySignal, ...]
    replayed: bool


@dataclass(frozen=True)
class FinalizationResult:
    capture: CaptureSession
    entry: Entry
    replayed: bool


def _language_enabled(language_tag: str, enabled_languages: list[str]) -> bool:
    normalized = language_tag.lower()
    base = normalized.split("-", 1)[0]
    return any(
        item.lower() == normalized or item.lower().split("-", 1)[0] == base
        for item in enabled_languages
    )


def _provider_language_supported(language_tag: str) -> bool:
    normalized = language_tag.lower()
    return (
        normalized in PROVIDER_LANGUAGE_TAGS
        or normalized.split("-", 1)[0] in PROVIDER_LANGUAGE_BASES
    )


def _capability_snapshot(enabled_languages: list[str]) -> dict:
    return {
        "adapter_mode": "provider_neutral_segment_event_contract",
        "audio_transcription_active": False,
        "clinic_enabled_languages": enabled_languages,
        "provider_supported_language_bases": sorted(PROVIDER_LANGUAGE_BASES),
        "provider_supported_language_tags": sorted(PROVIDER_LANGUAGE_TAGS),
        "unsupported_language_policy": "abstain_and_request_human_transcription",
        "speaker_attribution": "adapter_supplied_label_not_biometric_identity",
        "quality_policy": "segment_scores_visible_and_fail_closed",
    }


def start_capture(
    session: Session,
    *,
    actor: User,
    patient: Patient,
    interaction_type: str,
) -> CaptureSession:
    if patient.clinic_id != actor.clinic_id:
        raise CaptureContractError("capture_scope_mismatch", "Patient is outside actor clinic")
    if actor.role not in {"patient", "staff", "clinician"}:
        raise CaptureContractError("capture_role_required", "This role cannot start capture")
    if actor.role == "patient" and interaction_type != "patient_session":
        raise CaptureContractError(
            "patient_capture_scope",
            "A patient can start only a patient-session capture",
        )
    configuration = active_configuration(session, actor.clinic_id)
    if configuration is None:
        raise CaptureContractError(
            "clinic_configuration_unavailable",
            "No active clinic configuration is installed",
        )
    features = configuration.configuration["features"]
    if not features["streaming_capture"]:
        raise CaptureContractError(
            "streaming_capture_disabled",
            "Streaming capture is disabled for this clinic",
        )
    record = CaptureSession(
        clinic_id=actor.clinic_id,
        patient_id=patient.id,
        initiated_by=actor.id,
        interaction_type=interaction_type,
        status="streaming",
        latest_sequence=0,
        stream_contract_version=STREAM_CONTRACT_VERSION,
        capability_snapshot=_capability_snapshot(configuration.configuration["enabled_languages"]),
    )
    session.add(record)
    session.flush()
    append_audit(
        session,
        clinic_id=actor.clinic_id,
        actor_id=actor.id,
        action="capture.started",
        object_type="capture_session",
        object_id=record.id,
        metadata={
            "interaction_type": interaction_type,
            "stream_contract_version": STREAM_CONTRACT_VERSION,
        },
    )
    return record


def _input_hash(payload: StreamSegmentRequest) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _processing_assessment(
    payload: StreamSegmentRequest,
    capability_snapshot: dict,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    enabled = capability_snapshot["clinic_enabled_languages"]
    for span in payload.language_spans:
        tag = span.language_tag.lower()
        if not _provider_language_supported(tag):
            reasons.append(f"unsupported_provider_language:{tag}")
        elif not _language_enabled(tag, enabled):
            reasons.append(f"language_not_enabled_for_clinic:{tag}")
        if span.confidence < 0.55:
            reasons.append(f"very_low_language_confidence:{tag}")
        elif span.confidence < 0.75:
            reasons.append(f"low_language_confidence:{tag}")
    if payload.asr_confidence < 0.55:
        reasons.append("very_low_asr_confidence")
    elif payload.asr_confidence < 0.75:
        reasons.append("low_asr_confidence")
    if payload.audio_quality < 0.45:
        reasons.append("very_low_audio_quality")
    elif payload.audio_quality < 0.65:
        reasons.append("low_audio_quality")
    if payload.speaker_label in {"unknown", "overlap"}:
        reasons.append(f"speaker_{payload.speaker_label}")

    abstention_markers = (
        "unsupported_provider_language:",
        "language_not_enabled_for_clinic:",
        "very_low_",
    )
    if any(reason.startswith(abstention_markers) for reason in reasons):
        return "abstained", reasons
    if reasons:
        return "human_review_required", reasons
    return "supported", reasons


def _supported_character_mask(
    payload: StreamSegmentRequest,
    capability_snapshot: dict,
) -> str:
    characters = [" " for _ in payload.text]
    enabled = capability_snapshot["clinic_enabled_languages"]
    for span in payload.language_spans:
        tag = span.language_tag.lower()
        if _provider_language_supported(tag) and _language_enabled(tag, enabled):
            characters[span.start_offset : span.end_offset] = payload.text[
                span.start_offset : span.end_offset
            ]
    return "".join(characters)


def _is_negated(text: str, match_start: int) -> bool:
    prefix = text[max(0, match_start - 12) : match_start]
    return NEGATION_PATTERN.search(prefix) is not None


def _detect_safety_signals(
    session: Session,
    *,
    capture: CaptureSession,
    segment: TranscriptSegment,
    payload: StreamSegmentRequest,
) -> tuple[SafetySignal, ...]:
    supported_text = _supported_character_mask(payload, capture.capability_snapshot)
    evidence_quality = (
        "source_review_required"
        if payload.asr_confidence < 0.75 or payload.audio_quality < 0.65
        else "adapter_supported_unconfirmed"
    )
    findings: list[tuple[str, str, re.Match[str], str]] = []
    for match in ALLERGY_PATTERN.finditer(supported_text):
        if not _is_negated(supported_text, match.start()):
            findings.append(
                (
                    "allergy_mention",
                    match.group("substance").lower(),
                    match,
                    "critical",
                )
            )
    for match in MEDICATION_DOSE_PATTERN.finditer(supported_text):
        label = f"{match.group('drug').lower()} {match.group('dose')} {match.group('unit').lower()}"
        findings.append(
            (
                "medication_dose_mention",
                label,
                match,
                "high",
            )
        )

    signals: list[SafetySignal] = []
    for signal_type, label, match, severity in findings:
        signal = SafetySignal(
            clinic_id=capture.clinic_id,
            patient_id=capture.patient_id,
            capture_session_id=capture.id,
            source_segment_id=segment.id,
            signal_type=signal_type,
            normalized_label=label,
            evidence_quote=payload.text[match.start() : match.end()],
            source_start_offset=match.start(),
            source_end_offset=match.end(),
            severity=severity,
            evidence_quality=evidence_quality,
            review_state="provisional",
        )
        session.add(signal)
        signals.append(signal)
    session.flush()
    return tuple(signals)


def _withdraw_source_signals(session: Session, segment_id: str) -> None:
    for signal in session.scalars(
        select(SafetySignal).where(SafetySignal.source_segment_id == segment_id)
    ):
        signal.review_state = "source_retracted"
        signal.review_rationale = "The source segment was replaced by a later correction."
        signal.reviewed_at = datetime.now(UTC)


def add_segment(
    session: Session,
    *,
    actor: User,
    capture: CaptureSession,
    payload: StreamSegmentRequest,
) -> SegmentResult:
    if capture.clinic_id != actor.clinic_id:
        raise CaptureContractError("capture_scope_mismatch", "Capture is outside actor clinic")
    if capture.status != "streaming":
        raise CaptureContractError("capture_not_streaming", "Capture is no longer streaming")
    if actor.role not in {"staff", "clinician"} and actor.id != capture.initiated_by:
        raise CaptureContractError("capture_write_denied", "Actor cannot append to this capture")

    digest = _input_hash(payload)
    existing = session.scalar(
        select(TranscriptSegment).where(
            TranscriptSegment.capture_session_id == capture.id,
            TranscriptSegment.chunk_id == payload.chunk_id,
        )
    )
    if existing is not None:
        if existing.input_hash != digest:
            raise CaptureContractError(
                "segment_idempotency_collision",
                "This chunk ID was already used for different content",
            )
        signals = tuple(
            session.scalars(
                select(SafetySignal).where(SafetySignal.source_segment_id == existing.id)
            )
        )
        return SegmentResult(existing, signals, True)

    expected_sequence = capture.latest_sequence + 1
    if payload.sequence != expected_sequence:
        raise CaptureContractError(
            "segment_sequence_conflict",
            f"Expected sequence {expected_sequence}, received {payload.sequence}",
        )

    corrected: TranscriptSegment | None = None
    if payload.correction_of_segment_id is not None:
        corrected = session.scalar(
            select(TranscriptSegment).where(
                TranscriptSegment.id == payload.correction_of_segment_id,
                TranscriptSegment.capture_session_id == capture.id,
            )
        )
        if corrected is None or corrected.status == "retracted":
            raise CaptureContractError(
                "invalid_segment_correction",
                "The correction target is missing, outside this capture, or already retracted",
            )

    processing_state, processing_reasons = _processing_assessment(
        payload,
        capture.capability_snapshot,
    )
    segment = TranscriptSegment(
        clinic_id=capture.clinic_id,
        patient_id=capture.patient_id,
        capture_session_id=capture.id,
        correction_of_segment_id=None if corrected is None else corrected.id,
        chunk_id=payload.chunk_id,
        sequence=payload.sequence,
        start_ms=payload.start_ms,
        end_ms=payload.end_ms,
        speaker_label=payload.speaker_label,
        verbatim_text=payload.text,
        language_spans=[item.model_dump(mode="json") for item in payload.language_spans],
        asr_confidence=payload.asr_confidence,
        audio_quality=payload.audio_quality,
        processing_state=processing_state,
        processing_reasons=processing_reasons,
        status="provisional",
        input_hash=digest,
    )
    session.add(segment)
    session.flush()
    if corrected is not None:
        corrected.status = "retracted"
        _withdraw_source_signals(session, corrected.id)
    capture.latest_sequence = payload.sequence
    signals = _detect_safety_signals(
        session,
        capture=capture,
        segment=segment,
        payload=payload,
    )
    append_audit(
        session,
        clinic_id=capture.clinic_id,
        actor_id=actor.id,
        action="capture.segment_ingested",
        object_type="transcript_segment",
        object_id=segment.id,
        metadata={
            "capture_sequence": segment.sequence,
            "language_count": len(payload.language_spans),
            "processing_state": segment.processing_state,
            "safety_signal_count": len(signals),
            "source_corrected": corrected is not None,
        },
    )
    return SegmentResult(segment, signals, False)


def review_safety_signal(
    session: Session,
    *,
    actor: User,
    signal: SafetySignal,
    decision: str,
    rationale: str,
) -> SafetySignal:
    if signal.clinic_id != actor.clinic_id:
        raise CaptureContractError("capture_scope_mismatch", "Signal is outside actor clinic")
    if actor.role != "clinician":
        raise CaptureContractError(
            "clinician_confirmation_required",
            "Only a clinician can confirm or dismiss a safety signal",
        )
    if signal.review_state != "provisional":
        raise CaptureContractError(
            "signal_not_reviewable",
            "Only a provisional signal can be reviewed",
        )
    if decision not in {"confirm", "dismiss"}:
        raise CaptureContractError("invalid_review_decision", "Unknown review decision")
    signal.review_state = "confirmed" if decision == "confirm" else "dismissed"
    signal.review_rationale = rationale
    signal.reviewed_by = actor.id
    signal.reviewed_at = datetime.now(UTC)
    append_audit(
        session,
        clinic_id=signal.clinic_id,
        actor_id=actor.id,
        action="safety_signal.reviewed",
        object_type="safety_signal",
        object_id=signal.id,
        metadata={
            "review_decision": decision,
            "signal_type": signal.signal_type,
        },
    )
    return signal


def _masked_segment_text(segment: TranscriptSegment, capability_snapshot: dict) -> str:
    enabled = capability_snapshot["clinic_enabled_languages"]
    characters = list(segment.verbatim_text)
    replaced_tags: list[str] = []
    for span in segment.language_spans:
        tag = span["language_tag"].lower()
        if not _provider_language_supported(tag) or not _language_enabled(tag, enabled):
            characters[span["start_offset"] : span["end_offset"]] = [
                " " for _ in range(span["end_offset"] - span["start_offset"])
            ]
            replaced_tags.append(tag)
    supported = "".join(characters).strip()
    marker = ""
    if replaced_tags:
        unique = ", ".join(sorted(set(replaced_tags)))
        marker = f"[UNSUPPORTED LANGUAGE {unique} - HUMAN TRANSCRIPTION REQUIRED]"
    if segment.processing_state == "abstained" and not replaced_tags:
        return "[LOW-QUALITY SEGMENT - REVIEW SOURCE AUDIO]"
    if segment.processing_state == "human_review_required":
        marker = "[LOW-CONFIDENCE SEGMENT - VERIFY SOURCE AUDIO]"
    return " ".join(part for part in (supported, marker) if part)


def _draft_transcript(capture: CaptureSession, segments: list[TranscriptSegment]) -> str:
    lines = []
    for segment in segments:
        minutes, seconds = divmod(segment.start_ms // 1_000, 60)
        lines.append(
            f"[{minutes:02d}:{seconds:02d}] {segment.speaker_label}: "
            f"{_masked_segment_text(segment, capture.capability_snapshot)}"
        )
    return "\n".join(lines)


def finalize_capture(
    session: Session,
    *,
    actor: User,
    system_actor: User,
    patient: Patient,
    capture: CaptureSession,
    provider: ProviderGateway,
) -> FinalizationResult:
    if capture.clinic_id != actor.clinic_id or patient.clinic_id != actor.clinic_id:
        raise CaptureContractError("capture_scope_mismatch", "Capture is outside actor clinic")
    if capture.finalized_entry_id is not None:
        entry = session.get(Entry, capture.finalized_entry_id)
        if entry is None:
            raise CaptureContractError(
                "finalized_entry_missing",
                "The finalized capture points to a missing entry",
            )
        return FinalizationResult(capture, entry, True)
    if capture.status != "streaming":
        raise CaptureContractError("capture_not_streaming", "Capture is no longer streaming")
    if actor.role not in {"staff", "clinician"} and actor.id != capture.initiated_by:
        raise CaptureContractError("capture_write_denied", "Actor cannot finalize this capture")
    segments = list(
        session.scalars(
            select(TranscriptSegment)
            .where(
                TranscriptSegment.capture_session_id == capture.id,
                TranscriptSegment.status != "retracted",
            )
            .order_by(TranscriptSegment.sequence)
        )
    )
    if not segments:
        raise CaptureContractError(
            "capture_has_no_segments",
            "At least one active transcript segment is required",
        )
    transcript = _draft_transcript(capture, segments)
    result = ingest_scribe(
        session,
        initiating_actor=actor,
        system_actor=system_actor,
        patient=patient,
        interaction_type=capture.interaction_type,
        transcript=transcript,
        source_uri=f"capture://{capture.id}",
        provider=provider,
    )
    for segment in segments:
        segment.status = "final"
    capture.finalized_entry_id = result.entry.id
    capture.provider_status = result.provider_status
    capture.provider_failure_code = result.provider_failure_code
    capture.status = (
        "finalized_with_abstention"
        if any(segment.processing_state == "abstained" for segment in segments)
        else "finalized"
    )
    capture.finalized_at = datetime.now(UTC)
    append_audit(
        session,
        clinic_id=capture.clinic_id,
        actor_id=actor.id,
        action="capture.finalized",
        object_type="capture_session",
        object_id=capture.id,
        metadata={
            "processing_state": capture.status,
            "provider_status": result.provider_status,
            "provider_failure_code": result.provider_failure_code,
            "segment_count": len(segments),
        },
    )
    return FinalizationResult(capture, result.entry, False)


def serialize_segment(segment: TranscriptSegment) -> dict:
    return {
        "id": segment.id,
        "sequence": segment.sequence,
        "chunk_id": segment.chunk_id,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "speaker_label": segment.speaker_label,
        "text": segment.verbatim_text,
        "language_spans": segment.language_spans,
        "asr_confidence": segment.asr_confidence,
        "audio_quality": segment.audio_quality,
        "processing_state": segment.processing_state,
        "processing_reasons": segment.processing_reasons,
        "status": segment.status,
        "correction_of_segment_id": segment.correction_of_segment_id,
        "received_at": segment.received_at.isoformat(),
    }


def serialize_signal(signal: SafetySignal) -> dict:
    return {
        "id": signal.id,
        "source_segment_id": signal.source_segment_id,
        "signal_type": signal.signal_type,
        "normalized_label": signal.normalized_label,
        "evidence_quote": signal.evidence_quote,
        "source_start_offset": signal.source_start_offset,
        "source_end_offset": signal.source_end_offset,
        "severity": signal.severity,
        "evidence_quality": signal.evidence_quality,
        "review_state": signal.review_state,
        "review_rationale": signal.review_rationale,
        "reviewed_by": signal.reviewed_by,
        "detected_at": signal.detected_at.isoformat(),
        "reviewed_at": None if signal.reviewed_at is None else signal.reviewed_at.isoformat(),
    }


def serialize_capture(
    session: Session,
    capture: CaptureSession,
    *,
    include_clinical_signals: bool,
) -> dict:
    segments = list(
        session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.capture_session_id == capture.id)
            .order_by(TranscriptSegment.sequence)
        )
    )
    signals = list(
        session.scalars(
            select(SafetySignal)
            .where(SafetySignal.capture_session_id == capture.id)
            .order_by(SafetySignal.detected_at)
        )
    )
    return {
        "id": capture.id,
        "patient_id": capture.patient_id,
        "interaction_type": capture.interaction_type,
        "status": capture.status,
        "latest_sequence": capture.latest_sequence,
        "stream_contract_version": capture.stream_contract_version,
        "capabilities": capture.capability_snapshot,
        "segments": [serialize_segment(segment) for segment in segments],
        "safety_signals": (
            [serialize_signal(signal) for signal in signals] if include_clinical_signals else []
        ),
        "safety_signal_count": len(signals),
        "finalized_entry_id": capture.finalized_entry_id,
        "provider_status": capture.provider_status,
        "provider_failure_code": capture.provider_failure_code,
        "started_at": capture.started_at.isoformat(),
        "finalized_at": (
            None if capture.finalized_at is None else capture.finalized_at.isoformat()
        ),
        "assurance_boundary": (
            "This prototype ingests synthetic transcript segments through a provider-neutral "
            "contract; it does not perform or validate live audio ASR."
        ),
    }
