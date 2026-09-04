"""Build citation-first review answers from server-authorized clinical evidence.

The review copilot is deliberately deterministic in this local prototype. It
demonstrates the product contract expected from a future private model without
making network calls or allowing generated prose to outrun the source record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .importance import evidence_support_band
from .models import CareTask, Conflict, Entry, Highlight, ProvenanceSpan

MAX_CLAIMS = 4
MAX_ACTIONS = 3


@dataclass(frozen=True)
class ReviewClaim:
    """One review statement bound to the immutable span that supports it."""

    text: str
    risk_level: str
    risk_reason: str
    trust_state: str
    evidence_support: float
    evidence_support_band: str
    evidence_support_interpretation: str
    provenance_span_id: str
    source_entry_id: str
    quote: str


@dataclass(frozen=True)
class ReviewAction:
    """An open operational task with its owner and source entry."""

    title: str
    urgency: str
    assigned_to: str | None
    due_at: str | None
    source_entry_id: str | None


@dataclass(frozen=True)
class EvidenceReview:
    """A bounded answer that separates evidence, workflow, and uncertainty."""

    intent: str
    answer_state: str
    summary: str
    claims: tuple[ReviewClaim, ...]
    open_actions: tuple[ReviewAction, ...]
    conflicts: tuple[str, ...]
    abstention_reason: str | None
    provider: str
    safety_notice: str

    def to_dict(self) -> dict:
        """Return a JSON-ready response while preserving the explicit contract."""

        return asdict(self)


def classify_review_intent(question: str) -> str:
    """Map a natural-language question to a small, auditable review intent."""

    normalized = question.casefold()
    if any(term in normalized for term in ("medication", "medicine", "dose", "drug")):
        return "medication"
    if any(term in normalized for term in ("change", "different", "since")):
        return "change"
    if any(term in normalized for term in ("action", "next", "pending", "await", "follow")):
        return "action"
    if any(term in normalized for term in ("risk", "safety", "urgent", "allergy")):
        return "safety"
    return "overview"


def _intent_matches(intent: str, highlight: Highlight) -> bool:
    tags = set(highlight.entity_tags)
    if intent == "medication":
        return bool(tags & {"medication", "dose_change"})
    if intent == "change":
        return bool(tags & {"allergy", "dose_change", "symptom_change", "follow_up"})
    if intent == "action":
        return "follow_up" in tags
    if intent == "safety":
        return highlight.risk_level in {"critical", "high"}
    return True


def build_evidence_review(
    session: Session,
    *,
    clinic_id: str,
    patient_id: str,
    question: str,
) -> EvidenceReview:
    """Answer from ranked spans and workflow records without inventing facts."""

    intent = classify_review_intent(question)
    rows = session.execute(
        select(Highlight, ProvenanceSpan)
        .join(ProvenanceSpan)
        .join(Entry)
        .where(
            Highlight.clinic_id == clinic_id,
            Highlight.patient_id == patient_id,
            Highlight.status != "rejected",
            ProvenanceSpan.clinic_id == clinic_id,
            ProvenanceSpan.patient_id == patient_id,
            Entry.current_version_id == ProvenanceSpan.source_version_id,
        )
        .order_by(Highlight.rank_score.desc(), Highlight.created_at.desc())
    ).all()
    matching = [(highlight, span) for highlight, span in rows if _intent_matches(intent, highlight)]
    claims = tuple(
        ReviewClaim(
            text=highlight.title,
            risk_level=highlight.risk_level,
            risk_reason=highlight.risk_reason,
            trust_state=highlight.trust_state,
            evidence_support=highlight.evidence_support,
            evidence_support_band=evidence_support_band(highlight.evidence_support),
            evidence_support_interpretation=(
                "Policy-defined evidence support; not a calibrated probability of clinical "
                "correctness."
            ),
            provenance_span_id=span.id,
            source_entry_id=span.source_entry_id,
            quote=span.quote,
        )
        for highlight, span in matching[:MAX_CLAIMS]
    )

    tasks = list(
        session.scalars(
            select(CareTask)
            .where(
                CareTask.clinic_id == clinic_id,
                CareTask.patient_id == patient_id,
                CareTask.status == "open",
            )
            .order_by(CareTask.due_at)
            .limit(MAX_ACTIONS)
        )
    )
    actions = tuple(
        ReviewAction(
            title=task.title,
            urgency=task.urgency,
            assigned_to=task.assigned_to,
            due_at=task.due_at.isoformat() if task.due_at else None,
            source_entry_id=task.source_entry_id,
        )
        for task in tasks
    )
    conflicts = tuple(
        session.scalars(
            select(Conflict.summary)
            .where(
                Conflict.clinic_id == clinic_id,
                Conflict.patient_id == patient_id,
                Conflict.status == "open",
            )
            .order_by(Conflict.created_at.desc())
        )
    )

    if claims:
        summary = (
            f"Found {len(claims)} source-bound signal"
            f"{'s' if len(claims) != 1 else ''} for this {intent} review."
        )
        answer_state = "supported"
        abstention_reason = None
    elif intent == "action" and actions:
        summary = f"Found {len(actions)} open workflow action{'s' if len(actions) != 1 else ''}."
        answer_state = "workflow_only"
        abstention_reason = (
            "No matching clinical claim was asserted; only open workflow data is shown."
        )
    else:
        summary = "The available record does not support a source-bound answer to this question."
        answer_state = "insufficient_evidence"
        abstention_reason = "Review the timeline or add verified evidence before acting."

    return EvidenceReview(
        intent=intent,
        answer_state=answer_state,
        summary=summary,
        claims=claims,
        open_actions=actions,
        conflicts=conflicts,
        abstention_reason=abstention_reason,
        provider="local-evidence-reviewer-v1",
        safety_notice=(
            "This review organizes recorded evidence; it does not diagnose, prescribe, or confirm "
            "clinical truth. A qualified clinician must review every action."
        ),
    )
