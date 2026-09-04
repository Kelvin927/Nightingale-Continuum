"""Convert redacted interaction text into explicitly unconfirmed review drafts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import append_audit
from .care import create_entry
from .constants import AI_ENTRY_TYPES
from .importance import generate_highlights_for_entry
from .models import (
    CareTask,
    Conflict,
    Entry,
    Highlight,
    OutboundDelivery,
    Patient,
    SafetySignal,
    User,
)
from .providers import ProviderGateway, RedactedPayload, ScribeDraft
from .redaction import RedactionReceipt, redact_text


class RedactionFidelityError(ValueError):
    """Raised when privacy filtering cannot preserve clinical anchors exactly."""


class RegenerationError(ValueError):
    """Represent a stable refusal to regenerate outside the proposal layer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LocalDeterministicScribe:
    """A no-network demo provider used to prove the privacy boundary."""

    name = "local-deterministic-scribe"
    license = "Repository code; no external model"

    def __init__(self) -> None:
        self.last_received_text: str | None = None

    def generate(self, *, payload: RedactedPayload, interaction_type: str) -> ScribeDraft:
        self.last_received_text = payload.text
        lowered = payload.text.lower()
        flags: list[str] = ["human_review_required"]
        if any(term in lowered for term in ("medication", "dose", " mg", "allerg")):
            flags.append("medication_or_allergy_review")
        if any(term in lowered for term in ("ignore previous", "system prompt", "reveal secret")):
            flags.append("instruction_like_content_detected")
        label = interaction_type.replace("_", " ").title()
        non_placeholder_text = re.sub(r"<[^>]+>", " ", payload.text)
        meaningful_tokens = re.findall(r"[a-z0-9]+", non_placeholder_text.lower())
        uncertain_capture = len(meaningful_tokens) < 6 or any(
            marker in lowered
            for marker in ("[inaudible]", "unclear audio", "cannot determine", "not sure")
        )
        if uncertain_capture:
            flags.append("low_confidence_abstention")
            return ScribeDraft(
                title=f"AI abstention - {label}",
                content=(
                    "AI DRAFT ABSTAINED - HUMAN REVIEW REQUIRED\n\n"
                    "The captured interaction was too sparse or uncertain to support a "
                    "source-grounded draft. Review the source interaction directly.\n\n"
                    "No clinical fact has been asserted by this draft."
                ),
                confidence=0.35,
                flags=tuple(flags),
            )
        return ScribeDraft(
            title=f"AI draft - {label}",
            content=(
                "AI-GENERATED DRAFT - HUMAN REVIEW REQUIRED\n\n"
                f"Interaction: {label}\n"
                f"Source-grounded transcript extract: {payload.text.strip()}\n\n"
                "No clinical fact has been confirmed by this draft."
            ),
            confidence=0.82,
            flags=tuple(flags),
        )


@dataclass(frozen=True)
class ScribeIngestResult:
    entry: Entry
    receipt: RedactionReceipt
    provider_name: str
    provider_status: str
    provider_failure_code: str | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class RegenerationResult:
    result: ScribeIngestResult
    predecessor_entry_id: str
    protected_state_hash: str
    protected_highlight_count: int
    completed_task_count: int
    resolved_conflict_count: int
    released_delivery_count: int
    reviewed_signal_count: int


def _protected_state(session: Session, patient_id: str) -> dict[str, list[dict[str, object]]]:
    human_entries = list(
        session.scalars(
            select(Entry).where(Entry.patient_id == patient_id, Entry.owner_role != "system")
        )
    )
    decided_highlights = list(
        session.scalars(
            select(Highlight).where(
                Highlight.patient_id == patient_id,
                Highlight.status.in_(("accepted", "rejected", "pinned")),
            )
        )
    )
    completed_tasks = list(
        session.scalars(
            select(CareTask).where(
                CareTask.patient_id == patient_id,
                CareTask.status == "completed",
            )
        )
    )
    resolved_conflicts = list(
        session.scalars(
            select(Conflict).where(
                Conflict.patient_id == patient_id,
                Conflict.status != "open",
            )
        )
    )
    released_deliveries = list(
        session.scalars(select(OutboundDelivery).where(OutboundDelivery.patient_id == patient_id))
    )
    reviewed_signals = list(
        session.scalars(
            select(SafetySignal).where(
                SafetySignal.patient_id == patient_id,
                SafetySignal.review_state.in_(("confirmed", "dismissed")),
            )
        )
    )
    return {
        "human_entries": sorted(
            [
                {
                    "id": item.id,
                    "current_version_id": item.current_version_id,
                    "current_version": item.current_version,
                    "trust_state": item.trust_state,
                }
                for item in human_entries
            ],
            key=lambda item: str(item["id"]),
        ),
        "decided_highlights": sorted(
            [{"id": item.id, "status": item.status} for item in decided_highlights],
            key=lambda item: str(item["id"]),
        ),
        "completed_tasks": sorted(
            [{"id": item.id, "status": item.status} for item in completed_tasks],
            key=lambda item: str(item["id"]),
        ),
        "resolved_conflicts": sorted(
            [
                {
                    "id": item.id,
                    "status": item.status,
                    "disposition": item.disposition,
                    "resolved_by": item.resolved_by,
                }
                for item in resolved_conflicts
            ],
            key=lambda item: str(item["id"]),
        ),
        "released_deliveries": sorted(
            [
                {
                    "id": item.id,
                    "source_version_id": item.source_version_id,
                    "status": item.status,
                    "approved_by": item.approved_by,
                    "approval_evidence": item.approval_evidence,
                }
                for item in released_deliveries
            ],
            key=lambda item: str(item["id"]),
        ),
        "reviewed_signals": sorted(
            [{"id": item.id, "review_state": item.review_state} for item in reviewed_signals],
            key=lambda item: str(item["id"]),
        ),
    }


def _state_hash(state: dict[str, list[dict[str, object]]]) -> str:
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def ingest_scribe(
    session: Session,
    *,
    initiating_actor: User,
    system_actor: User,
    patient: Patient,
    interaction_type: str,
    transcript: str,
    source_uri: str,
    provider: ProviderGateway,
) -> ScribeIngestResult:
    if interaction_type not in AI_ENTRY_TYPES:
        raise ValueError("Unsupported interaction type")
    known_names = [patient.display_name, initiating_actor.display_name]
    redaction = redact_text(transcript, known_names=known_names)
    if not redaction.receipt.passed:
        raise RedactionFidelityError(
            "Redaction did not preserve every safety-relevant clinical anchor"
        )
    payload = RedactedPayload(
        text=redaction.text,
        sanitized_sha256=redaction.receipt.sanitized_sha256,
        detector_version=redaction.receipt.detector_version,
        clinical_anchor_count=redaction.receipt.clinical_anchor_count,
        receipt_passed=redaction.receipt.passed,
        purpose=interaction_type,
    )
    outcome = provider.generate(payload=payload, interaction_type=interaction_type)
    draft = outcome.draft
    entry = create_entry(
        session,
        actor=system_actor,
        clinic_id=patient.clinic_id,
        patient_id=patient.id,
        owner_role="system",
        entry_type=AI_ENTRY_TYPES[interaction_type],
        title=draft.title,
        content=draft.content,
        visibility="internal",
        trust_state="ai_proposed",
        source_uri=source_uri,
        change_reason="Generated from a redacted synthetic interaction",
    )
    if draft.confidence >= 0.6:
        generate_highlights_for_entry(session, entry=entry)
    append_audit(
        session,
        clinic_id=patient.clinic_id,
        actor_id=initiating_actor.id,
        action="scribe.ingested",
        object_type="entry",
        object_id=entry.id,
        object_version=1,
        metadata={
            "interaction_type": interaction_type,
            "provider": outcome.provider_name,
            "provider_status": outcome.status,
            "provider_failure_code": outcome.failure_code,
            "redaction_detector": redaction.receipt.detector_version,
            "redaction_entity_counts": redaction.receipt.entity_counts,
            "flag_count": len(draft.flags),
        },
    )
    return ScribeIngestResult(
        entry,
        redaction.receipt,
        outcome.provider_name,
        outcome.status,
        outcome.failure_code,
        draft.flags,
    )


def regenerate_scribe(
    session: Session,
    *,
    initiating_actor: User,
    system_actor: User,
    patient: Patient,
    predecessor: Entry,
    expected_version: int,
    transcript: str,
    source_uri: str,
    provider: ProviderGateway,
) -> RegenerationResult:
    """Create a new AI proposal while proving protected human state is unchanged."""

    if predecessor.clinic_id != initiating_actor.clinic_id or patient.clinic_id != (
        initiating_actor.clinic_id
    ):
        raise RegenerationError("regeneration_scope_mismatch", "Entry is outside actor clinic")
    if predecessor.patient_id != patient.id:
        raise RegenerationError("regeneration_patient_mismatch", "Entry belongs to another patient")
    if predecessor.owner_role != "system" or predecessor.trust_state != "ai_proposed":
        raise RegenerationError(
            "proposal_layer_required",
            "Only an unconfirmed AI proposal can be regenerated",
        )
    interaction_type = next(
        (key for key, value in AI_ENTRY_TYPES.items() if value == predecessor.entry_type),
        None,
    )
    if interaction_type is None:
        raise RegenerationError("unsupported_ai_entry_type", "AI entry type cannot be regenerated")
    if predecessor.current_version != expected_version:
        raise RegenerationError(
            "regeneration_version_conflict",
            "The predecessor changed after regeneration review",
        )

    before = _protected_state(session, patient.id)
    before_hash = _state_hash(before)
    result = ingest_scribe(
        session,
        initiating_actor=initiating_actor,
        system_actor=system_actor,
        patient=patient,
        interaction_type=interaction_type,
        transcript=transcript,
        source_uri=source_uri,
        provider=provider,
    )
    after_hash = _state_hash(_protected_state(session, patient.id))
    if after_hash != before_hash:
        raise RegenerationError(
            "protected_state_changed",
            "Regeneration attempted to change human-protected state",
        )
    receipt = RegenerationResult(
        result=result,
        predecessor_entry_id=predecessor.id,
        protected_state_hash=before_hash,
        protected_highlight_count=len(before["decided_highlights"]),
        completed_task_count=len(before["completed_tasks"]),
        resolved_conflict_count=len(before["resolved_conflicts"]),
        released_delivery_count=len(before["released_deliveries"]),
        reviewed_signal_count=len(before["reviewed_signals"]),
    )
    append_audit(
        session,
        clinic_id=patient.clinic_id,
        actor_id=initiating_actor.id,
        action="scribe.regenerated",
        object_type="entry",
        object_id=result.entry.id,
        object_version=1,
        metadata={
            "predecessor_entry_id": predecessor.id,
            "protected_state_hash": before_hash,
            "protected_highlight_count": receipt.protected_highlight_count,
            "completed_task_count": receipt.completed_task_count,
            "resolved_conflict_count": receipt.resolved_conflict_count,
            "released_delivery_count": receipt.released_delivery_count,
            "reviewed_signal_count": receipt.reviewed_signal_count,
        },
    )
    return receipt


def receipt_dict(receipt: RedactionReceipt) -> dict:
    return asdict(receipt)
