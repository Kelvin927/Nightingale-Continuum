"""Convert redacted interaction text into explicitly unconfirmed review drafts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from .audit import append_audit
from .care import create_entry
from .constants import AI_ENTRY_TYPES
from .importance import generate_highlights_for_entry
from .models import Entry, Patient, User
from .redaction import RedactionReceipt, redact_text


@dataclass(frozen=True)
class ScribeDraft:
    title: str
    content: str
    confidence: float
    flags: tuple[str, ...]


class LocalDeterministicScribe:
    """A no-network demo provider used to prove the privacy boundary."""

    name = "local-deterministic-scribe"
    license = "Repository code; no external model"

    def __init__(self) -> None:
        self.last_received_text: str | None = None

    def generate(self, *, redacted_text: str, interaction_type: str) -> ScribeDraft:
        self.last_received_text = redacted_text
        lowered = redacted_text.lower()
        flags: list[str] = ["human_review_required"]
        if any(term in lowered for term in ("medication", "dose", " mg", "allerg")):
            flags.append("medication_or_allergy_review")
        if any(term in lowered for term in ("ignore previous", "system prompt", "reveal secret")):
            flags.append("instruction_like_content_detected")
        label = interaction_type.replace("_", " ").title()
        non_placeholder_text = re.sub(r"<[^>]+>", " ", redacted_text)
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
                f"Source-grounded transcript extract: {redacted_text.strip()}\n\n"
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
    flags: tuple[str, ...]


def ingest_scribe(
    session: Session,
    *,
    initiating_actor: User,
    system_actor: User,
    patient: Patient,
    interaction_type: str,
    transcript: str,
    source_uri: str,
    provider: LocalDeterministicScribe,
) -> ScribeIngestResult:
    if interaction_type not in AI_ENTRY_TYPES:
        raise ValueError("Unsupported interaction type")
    known_names = [patient.display_name, initiating_actor.display_name]
    redaction = redact_text(transcript, known_names=known_names)
    draft = provider.generate(redacted_text=redaction.text, interaction_type=interaction_type)
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
        generate_highlights_for_entry(session, entry=entry, actor_role=initiating_actor.role)
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
            "provider": provider.name,
            "redaction_detector": redaction.receipt.detector_version,
            "redaction_entity_counts": redaction.receipt.entity_counts,
            "flag_count": len(draft.flags),
        },
    )
    return ScribeIngestResult(entry, redaction.receipt, provider.name, draft.flags)


def receipt_dict(receipt: RedactionReceipt) -> dict:
    return asdict(receipt)
