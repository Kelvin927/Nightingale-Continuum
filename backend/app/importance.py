from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import append_audit
from .care import current_version
from .constants import POLICY_VERSION, RISK_ORDER, RISK_WEIGHT, SAFETY_ENTITY_TAGS
from .models import (
    CareTask,
    Entry,
    FeaturePosterior,
    Highlight,
    ImportanceFeedback,
    ProvenanceSpan,
    User,
)
from .provenance import create_span

SENTENCE_PATTERN = re.compile(r"[^.!?\n]+(?:[.!?]|$)")


def _classify_sentence(sentence: str) -> tuple[str, list[str], str, str] | None:
    lowered = sentence.lower()
    tags: set[str] = set()
    risk_level = "low"
    title = "Context to review"
    reason = "Relevant longitudinal context"

    if any(term in lowered for term in ("allerg", "anaphyl", "facial swelling")):
        tags.add("allergy")
        risk_level = "critical"
        title = "Allergy safety signal"
        reason = "Allergy or severe reaction language requires prominent review"
    if any(term in lowered for term in ("chest pain", "shortness of breath", "suicidal")):
        tags.add("critical_result")
        risk_level = "critical"
        title = "Critical symptom signal"
        reason = "Potentially urgent symptom language requires clinician review"
    if any(term in lowered for term in ("medication", "dose", "mg", "lisinopril", "metformin")):
        tags.add("medication")
        if any(term in lowered for term in ("changed", "increase", "decrease", "from ")):
            tags.add("dose_change")
        if risk_level != "critical":
            risk_level = "high"
            title = "Medication detail to reconcile"
            reason = "Medication or dose information is a known high-risk scribe error class"
    if any(term in lowered for term in ("worsen", "dizz", "faint", "new symptom")):
        tags.add("symptom_change")
        if RISK_ORDER[risk_level] > RISK_ORDER["high"]:
            risk_level = "high"
            title = "Symptom change"
            reason = "A new or worsening symptom may change the care plan"
    if any(term in lowered for term in ("follow-up", "follow up", "lab", "pending", "await")):
        tags.add("follow_up")
        if RISK_ORDER[risk_level] > RISK_ORDER["medium"]:
            risk_level = "medium"
            title = "Open follow-up"
            reason = "An unresolved follow-up may require ownership or action"
    if any(term in lowered for term in ("diagnos", "assessment", "history")):
        tags.add("clinical_context")

    if not tags:
        return None
    return risk_level, sorted(tags), title, reason


def _age_days(value: datetime, now: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max(0.0, (now - value).total_seconds() / 86_400)


def base_score(
    *,
    risk_level: str,
    tags: list[str],
    created_at: datetime,
    now: datetime | None = None,
    unresolved_action: bool = False,
    explicitly_pinned: bool = False,
) -> tuple[float, dict[str, float]]:
    reference_time = now or datetime.now(UTC)
    factors = {
        "risk": RISK_WEIGHT[risk_level],
        "entity_safety": 1.5 if SAFETY_ENTITY_TAGS & set(tags) else 0.0,
        "recency": round(1.5 * math.exp(-_age_days(created_at, reference_time) / 120), 4),
        "unresolved_action": 2.0 if unresolved_action else 0.0,
        "explicit_pin": 1.25 if explicitly_pinned else 0.0,
    }
    return round(sum(factors.values()), 4), factors


def _posterior(
    session: Session,
    *,
    clinic_id: str,
    actor_role: str,
    feature: str,
    create: bool,
) -> FeaturePosterior | None:
    item = session.scalar(
        select(FeaturePosterior).where(
            FeaturePosterior.clinic_id == clinic_id,
            FeaturePosterior.actor_role == actor_role,
            FeaturePosterior.feature == feature,
        )
    )
    if item is None and create:
        item = FeaturePosterior(
            clinic_id=clinic_id,
            actor_role=actor_role,
            feature=feature,
            alpha=2.0,
            beta=2.0,
        )
        session.add(item)
        session.flush()
    return item


def adaptive_score(
    session: Session,
    *,
    clinic_id: str,
    actor_role: str,
    features: list[str],
) -> float:
    contribution = 0.0
    for feature in sorted(set(features)):
        role_item = _posterior(
            session,
            clinic_id=clinic_id,
            actor_role=actor_role,
            feature=feature,
            create=False,
        )
        global_item = _posterior(
            session,
            clinic_id=clinic_id,
            actor_role="all",
            feature=feature,
            create=False,
        )
        role_mean = (
            0.5 if role_item is None else role_item.alpha / (role_item.alpha + role_item.beta)
        )
        global_mean = (
            0.5
            if global_item is None
            else global_item.alpha / (global_item.alpha + global_item.beta)
        )
        pooled_mean = 0.6 * role_mean + 0.4 * global_mean
        contribution += 1.5 * (pooled_mean - 0.5)
    return round(max(-0.75, min(0.75, contribution)), 4)


def generate_highlights_for_entry(
    session: Session,
    *,
    entry: Entry,
    actor_role: str = "clinician",
) -> list[Highlight]:
    version = current_version(session, entry)
    highlights: list[Highlight] = []
    for match in SENTENCE_PATTERN.finditer(version.content):
        sentence = match.group().strip()
        if not sentence:
            continue
        leading_space = len(match.group()) - len(match.group().lstrip())
        start = match.start() + leading_space
        end = start + len(sentence)
        classified = _classify_sentence(sentence)
        if classified is None:
            continue
        risk_level, tags, title, reason = classified
        existing_span = session.scalar(
            select(ProvenanceSpan).where(
                ProvenanceSpan.source_version_id == version.id,
                ProvenanceSpan.start_offset == start,
                ProvenanceSpan.end_offset == end,
            )
        )
        if existing_span is not None:
            existing = session.scalar(
                select(Highlight).where(Highlight.provenance_span_id == existing_span.id)
            )
            if existing is not None:
                highlights.append(existing)
                continue
        span = create_span(
            session,
            entry=entry,
            version=version,
            start_offset=start,
            end_offset=end,
        )
        score, factors = base_score(
            risk_level=risk_level,
            tags=tags,
            created_at=entry.created_at,
        )
        learned = adaptive_score(
            session,
            clinic_id=entry.clinic_id,
            actor_role=actor_role,
            features=tags,
        )
        highlight = Highlight(
            clinic_id=entry.clinic_id,
            patient_id=entry.patient_id,
            provenance_span_id=span.id,
            title=title,
            risk_level=risk_level,
            risk_reason=reason,
            entity_tags=tags,
            confidence=0.88 if entry.owner_role == "system" else 0.98,
            trust_state=entry.trust_state,
            status="suggested" if entry.owner_role == "system" else "accepted",
            base_score=score,
            adaptive_score=learned,
            rank_score=round(score + learned, 4),
            score_factors=factors,
            policy_version=POLICY_VERSION,
            created_at=entry.created_at,
        )
        session.add(highlight)
        session.flush()
        highlights.append(highlight)
    return highlights


def _update_posterior(item: FeaturePosterior, reward: float) -> None:
    item.alpha += reward
    item.beta += 1.0 - reward
    item.observations += 1
    item.updated_at = datetime.now(UTC)


def record_feedback(
    session: Session,
    *,
    actor: User,
    highlight: Highlight,
    action: str,
    display_propensity: float,
) -> ImportanceFeedback:
    if actor.role not in {"staff", "clinician"}:
        raise ValueError("Only staff and clinicians can train importance ranking")
    if action not in {"accept", "reject", "pin"}:
        raise ValueError("Unsupported feedback action")
    if not 0 < display_propensity <= 1:
        raise ValueError("Display propensity must be in (0, 1]")
    reward = 1.0 if action in {"accept", "pin"} else 0.0
    context = {
        "features": sorted(highlight.entity_tags),
        "risk_level": highlight.risk_level,
        "base_score": highlight.base_score,
        "position_score": highlight.rank_score,
    }
    feedback = ImportanceFeedback(
        clinic_id=actor.clinic_id,
        highlight_id=highlight.id,
        actor_id=actor.id,
        action=action,
        reward=reward,
        policy_version=highlight.policy_version,
        display_propensity=display_propensity,
        context=context,
    )
    session.add(feedback)
    for role_key in (actor.role, "all"):
        for feature in sorted(set(highlight.entity_tags)):
            item = _posterior(
                session,
                clinic_id=actor.clinic_id,
                actor_role=role_key,
                feature=feature,
                create=True,
            )
            assert item is not None
            _update_posterior(item, reward)
    highlight.status = {"accept": "accepted", "reject": "rejected", "pin": "pinned"}[action]
    refresh_adaptive_scores(session, actor.clinic_id, actor.role)
    append_audit(
        session,
        clinic_id=actor.clinic_id,
        actor_id=actor.id,
        action="highlight.feedback_recorded",
        object_type="highlight",
        object_id=highlight.id,
        metadata={
            "feedback_action": action,
            "policy_version": highlight.policy_version,
            "feature_count": len(highlight.entity_tags),
        },
    )
    return feedback


def refresh_adaptive_scores(session: Session, clinic_id: str, actor_role: str) -> None:
    for highlight in session.scalars(select(Highlight).where(Highlight.clinic_id == clinic_id)):
        learned = adaptive_score(
            session,
            clinic_id=clinic_id,
            actor_role=actor_role,
            features=highlight.entity_tags,
        )
        highlight.adaptive_score = learned
        highlight.rank_score = round(highlight.base_score + learned, 4)


def _rank_key(highlight: Highlight) -> tuple[int, int, float, datetime]:
    safety_band = 0 if SAFETY_ENTITY_TAGS & set(highlight.entity_tags) else 1
    return (
        RISK_ORDER[highlight.risk_level],
        safety_band,
        -highlight.rank_score,
        -highlight.created_at.timestamp(),
    )


def ranked_highlights(session: Session, patient_id: str, limit: int = 6) -> list[Highlight]:
    candidates = list(
        session.scalars(
            select(Highlight).where(
                Highlight.patient_id == patient_id,
                Highlight.status != "rejected",
            )
        )
    )
    return sorted(candidates, key=_rank_key)[:limit]


def build_glance_projection(session: Session, patient_id: str) -> dict:
    highlights = ranked_highlights(session, patient_id)
    tasks = list(
        session.scalars(
            select(CareTask)
            .where(CareTask.patient_id == patient_id, CareTask.status == "open")
            .order_by(CareTask.due_at)
        )
    )
    grouped = {"act_now": [], "watch": [], "awaiting": []}
    for item in highlights:
        bucket = "act_now" if item.risk_level in {"critical", "high"} else "watch"
        grouped[bucket].append(
            {
                "id": item.id,
                "title": item.title,
                "risk_level": item.risk_level,
                "risk_reason": item.risk_reason,
                "entity_tags": item.entity_tags,
                "confidence": item.confidence,
                "trust_state": item.trust_state,
                "status": item.status,
                "rank_score": item.rank_score,
                "score_factors": {**item.score_factors, "adaptive": item.adaptive_score},
                "provenance_span_id": item.provenance_span_id,
                "policy_version": item.policy_version,
            }
        )
    for task in tasks[:3]:
        grouped["awaiting"].append(
            {
                "id": task.id,
                "title": task.title,
                "urgency": task.urgency,
                "assigned_to": task.assigned_to,
                "due_at": task.due_at.isoformat() if task.due_at else None,
                "source_entry_id": task.source_entry_id,
            }
        )
    return {
        "groups": grouped,
        "item_budget": 9,
        "generated_at": datetime.now(UTC).isoformat(),
        "policy_version": POLICY_VERSION,
        "safety_rule": (
            "Critical risks and medication/allergy safety items outrank learned adjustments."
        ),
    }
