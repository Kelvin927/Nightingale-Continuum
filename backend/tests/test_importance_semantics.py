from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import importance as importance_module
from app.care import create_entry, current_version
from app.constants import POLICY_VERSION
from app.importance import (
    _age_days,
    _classify_sentence,
    _posterior,
    _rank_key,
    adaptive_score,
    base_score,
    build_glance_projection,
    generate_highlights_for_entry,
    ranked_highlights,
    record_feedback,
    refresh_adaptive_scores,
)
from app.models import (
    AuditEvent,
    CareTask,
    FeaturePosterior,
    Highlight,
    Patient,
    ProvenanceSpan,
    User,
)
from app.provenance import create_span
from app.seed import OTHER_PATIENT_ID


def test_generated_highlights_and_source_spans_have_an_exact_persisted_contract(
    app, identities, patient_id, monkeypatch
):
    reference_time = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, timezone=None):
            assert timezone is UTC
            return reference_time

    monkeypatch.setattr(importance_module, "datetime", FixedDateTime)
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        patient = session.get(Patient, patient_id)
        assert actor is not None and patient is not None
        entry = create_entry(
            session,
            actor=actor,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="system",
            entry_type="ai_doctor_consult_summary",
            title="Exact generated highlight contract",
            content="Medication increased.\nFollow-up pending.",
            visibility="internal",
            trust_state="ai_proposed",
            source_uri="session://exact-highlight-generation",
            created_at=reference_time,
        )
        highlights = generate_highlights_for_entry(session, entry=entry, actor_role="clinician")
        assert len(highlights) == 2
        medication, follow_up = highlights
        assert (
            medication.clinic_id,
            medication.patient_id,
            medication.title,
            medication.risk_level,
            medication.risk_reason,
            medication.entity_tags,
            medication.confidence,
            medication.trust_state,
            medication.status,
            medication.base_score,
            medication.adaptive_score,
            medication.rank_score,
            medication.score_factors,
            medication.policy_version,
            medication.created_at,
        ) == (
            patient.clinic_id,
            patient.id,
            "Medication detail to reconcile",
            "high",
            "Medication or dose information is a known high-risk scribe error class",
            ["dose_change", "medication"],
            0.88,
            "ai_proposed",
            "suggested",
            8.0,
            0.0,
            8.0,
            {
                "risk": 5.0,
                "entity_safety": 1.5,
                "recency": 1.5,
                "unresolved_action": 0.0,
                "explicit_pin": 0.0,
            },
            POLICY_VERSION,
            reference_time,
        )
        assert (
            follow_up.title,
            follow_up.risk_level,
            follow_up.risk_reason,
            follow_up.entity_tags,
            follow_up.confidence,
            follow_up.status,
            follow_up.base_score,
            follow_up.adaptive_score,
            follow_up.rank_score,
            follow_up.score_factors,
        ) == (
            "Open follow-up",
            "medium",
            "An unresolved follow-up may require ownership or action",
            ["follow_up"],
            0.88,
            "suggested",
            4.0,
            0.0,
            4.0,
            {
                "risk": 2.5,
                "entity_safety": 0.0,
                "recency": 1.5,
                "unresolved_action": 0.0,
                "explicit_pin": 0.0,
            },
        )
        medication_span = session.get(ProvenanceSpan, medication.provenance_span_id)
        follow_up_span = session.get(ProvenanceSpan, follow_up.provenance_span_id)
        assert medication_span is not None and follow_up_span is not None
        assert (
            medication_span.source_entry_id,
            medication_span.source_version_id,
            medication_span.start_offset,
            medication_span.end_offset,
            medication_span.quote,
            medication_span.source_kind,
            medication_span.source_uri,
        ) == (
            entry.id,
            entry.current_version_id,
            0,
            21,
            "Medication increased.",
            "ai_doctor_consult_summary",
            "session://exact-highlight-generation",
        )
        assert (
            follow_up_span.start_offset,
            follow_up_span.end_offset,
            follow_up_span.quote,
        ) == (22, 40, "Follow-up pending.")
        assert _rank_key(medication) == (1, 0, -8.0, -reference_time.timestamp())
        assert _rank_key(follow_up) == (2, 1, -4.0, -reference_time.timestamp())


def test_feedback_persists_exact_context_updates_both_posteriors_and_audit(
    app, identities, patient_id
):
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        highlight = next(
            item
            for item in session.scalars(select(Highlight).where(Highlight.patient_id == patient_id))
            if len(item.entity_tags) >= 2
        )
        assert actor is not None
        displayed_position_score = highlight.rank_score
        feedback = record_feedback(
            session,
            actor=actor,
            highlight=highlight,
            action="accept",
            display_propensity=0.37,
        )
        assert (
            feedback.clinic_id,
            feedback.highlight_id,
            feedback.actor_id,
            feedback.action,
            feedback.reward,
            feedback.policy_version,
            feedback.display_propensity,
            feedback.context,
            highlight.status,
        ) == (
            actor.clinic_id,
            highlight.id,
            actor.id,
            "accept",
            1.0,
            highlight.policy_version,
            0.37,
            {
                "features": sorted(highlight.entity_tags),
                "risk_level": highlight.risk_level,
                "base_score": highlight.base_score,
                "position_score": displayed_position_score,
            },
            "accepted",
        )
        posteriors = list(
            session.scalars(
                select(FeaturePosterior).where(
                    FeaturePosterior.clinic_id == actor.clinic_id,
                    FeaturePosterior.feature.in_(highlight.entity_tags),
                )
            )
        )
        assert len(posteriors) == 2 * len(set(highlight.entity_tags))
        assert {(item.actor_role, item.feature) for item in posteriors} == {
            (role, feature)
            for role in (actor.role, "all")
            for feature in set(highlight.entity_tags)
        }
        assert all(
            (item.alpha, item.beta, item.observations) == (3.0, 2.0, 1) for item in posteriors
        )
        expected_adaptive = round(0.15 * len(set(highlight.entity_tags)), 4)
        assert highlight.adaptive_score == expected_adaptive
        assert highlight.rank_score == round(highlight.base_score + expected_adaptive, 4)
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.object_id == highlight.id,
                AuditEvent.action == "highlight.feedback_recorded",
            )
        )
        assert event is not None
        assert (
            event.clinic_id,
            event.actor_id,
            event.object_type,
            event.object_version,
            event.event_metadata,
        ) == (
            actor.clinic_id,
            actor.id,
            "highlight",
            None,
            {
                "feedback_action": "accept",
                "policy_version": highlight.policy_version,
                "feature_count": len(highlight.entity_tags),
            },
        )

        for action, propensity, message in (
            ("unsupported", 0.5, "Unsupported feedback action"),
            ("accept", 0.0, "Display propensity must be in (0, 1]"),
            ("accept", 1.01, "Display propensity must be in (0, 1]"),
        ):
            with pytest.raises(ValueError) as error:
                record_feedback(
                    session,
                    actor=actor,
                    highlight=highlight,
                    action=action,
                    display_propensity=propensity,
                )
            assert error.value.args == (message,)


def test_glance_projection_is_an_exact_bounded_projection_of_ranked_domain_rows(app, patient_id):
    with app.state.database.session() as session:
        projection = build_glance_projection(session, patient_id)
        assert set(projection) == {
            "groups",
            "item_budget",
            "generated_at",
            "policy_version",
            "safety_rule",
        }
        assert projection["item_budget"] == 9
        assert projection["policy_version"] == POLICY_VERSION
        assert projection["safety_rule"] == (
            "Critical risks and medication/allergy safety items outrank learned adjustments."
        )
        assert datetime.fromisoformat(projection["generated_at"]).tzinfo is not None
        groups = projection["groups"]
        assert set(groups) == {"act_now", "watch", "awaiting"}

        domain_highlights = ranked_highlights(session, patient_id)
        projected_highlights = groups["act_now"] + groups["watch"]
        assert [item["id"] for item in projected_highlights] == [
            item.id for item in domain_highlights
        ]
        expected_highlight_keys = {
            "id",
            "title",
            "risk_level",
            "risk_reason",
            "entity_tags",
            "confidence",
            "trust_state",
            "status",
            "rank_score",
            "score_factors",
            "provenance_span_id",
            "policy_version",
        }
        for projected, domain in zip(projected_highlights, domain_highlights, strict=True):
            assert set(projected) == expected_highlight_keys
            assert projected == {
                "id": domain.id,
                "title": domain.title,
                "risk_level": domain.risk_level,
                "risk_reason": domain.risk_reason,
                "entity_tags": domain.entity_tags,
                "confidence": domain.confidence,
                "trust_state": domain.trust_state,
                "status": domain.status,
                "rank_score": domain.rank_score,
                "score_factors": {**domain.score_factors, "adaptive": domain.adaptive_score},
                "provenance_span_id": domain.provenance_span_id,
                "policy_version": domain.policy_version,
            }

        tasks = list(
            session.scalars(
                select(CareTask)
                .where(CareTask.patient_id == patient_id, CareTask.status == "open")
                .order_by(CareTask.due_at)
            )
        )[:3]
        assert groups["awaiting"] == [
            {
                "id": task.id,
                "title": task.title,
                "urgency": task.urgency,
                "assigned_to": task.assigned_to,
                "due_at": task.due_at.isoformat() if task.due_at else None,
                "source_entry_id": task.source_entry_id,
            }
            for task in tasks
        ]


def test_scoring_edges_are_exact_clinic_scoped_and_safety_bounded(app):
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    assert _age_days(now - timedelta(days=1), now) == 1.0
    assert _age_days(now + timedelta(days=1), now) == 0.0
    assert _classify_sentence("Medication dose changed and symptoms worsened.") == (
        "high",
        ["dose_change", "medication", "symptom_change"],
        "Medication detail to reconcile",
        "Medication or dose information is a known high-risk scribe error class",
    )
    score, factors = base_score(
        risk_level="high",
        tags=["medication"],
        created_at=now - timedelta(days=1),
        now=now,
        unresolved_action=True,
        explicitly_pinned=True,
    )
    assert factors == {
        "risk": 5.0,
        "entity_safety": 1.5,
        "recency": 1.4876,
        "unresolved_action": 2.0,
        "explicit_pin": 1.25,
    }
    assert score == 11.2376

    with app.state.database.session() as session:
        session.add_all(
            [
                FeaturePosterior(
                    clinic_id="clinic-riverside",
                    actor_role="clinician",
                    feature="clinic-scope",
                    alpha=99.0,
                    beta=1.0,
                ),
                FeaturePosterior(
                    clinic_id="clinic-northstar",
                    actor_role="clinician",
                    feature="clinic-scope",
                    alpha=3.0,
                    beta=7.0,
                ),
            ]
        )
        for feature in ("positive-a", "positive-b"):
            session.add_all(
                [
                    FeaturePosterior(
                        clinic_id="clinic-northstar",
                        actor_role="clinician",
                        feature=feature,
                        alpha=999.0,
                        beta=1.0,
                    ),
                    FeaturePosterior(
                        clinic_id="clinic-northstar",
                        actor_role="all",
                        feature=feature,
                        alpha=999.0,
                        beta=1.0,
                    ),
                ]
            )
        for feature in ("negative-a", "negative-b"):
            session.add_all(
                [
                    FeaturePosterior(
                        clinic_id="clinic-northstar",
                        actor_role="clinician",
                        feature=feature,
                        alpha=1.0,
                        beta=999.0,
                    ),
                    FeaturePosterior(
                        clinic_id="clinic-northstar",
                        actor_role="all",
                        feature=feature,
                        alpha=1.0,
                        beta=999.0,
                    ),
                ]
            )
        session.add_all(
            [
                FeaturePosterior(
                    clinic_id="clinic-northstar",
                    actor_role="clinician",
                    feature="rounding-contract",
                    alpha=2.0,
                    beta=5.0,
                ),
                FeaturePosterior(
                    clinic_id="clinic-northstar",
                    actor_role="all",
                    feature="rounding-contract",
                    alpha=3.0,
                    beta=7.0,
                ),
            ]
        )
        session.flush()
        scoped = _posterior(
            session,
            clinic_id="clinic-northstar",
            actor_role="clinician",
            feature="clinic-scope",
            create=False,
        )
        assert scoped is not None
        assert (scoped.clinic_id, scoped.alpha, scoped.beta) == (
            "clinic-northstar",
            3.0,
            7.0,
        )
        assert (
            adaptive_score(
                session,
                clinic_id="clinic-northstar",
                actor_role="clinician",
                features=["positive-a", "positive-b"],
            )
            == 0.75
        )
        assert (
            adaptive_score(
                session,
                clinic_id="clinic-northstar",
                actor_role="clinician",
                features=["negative-a", "negative-b"],
            )
            == -0.75
        )
        assert (
            adaptive_score(
                session,
                clinic_id="clinic-northstar",
                actor_role="clinician",
                features=["rounding-contract"],
            )
            == -0.3129
        )


def test_highlight_generation_handles_whitespace_learning_reuse_and_span_identity(
    app, identities, patient_id
):
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        patient = session.get(Patient, patient_id)
        assert actor is not None and patient is not None
        session.add_all(
            [
                FeaturePosterior(
                    clinic_id=patient.clinic_id,
                    actor_role="clinician",
                    feature="medication",
                    alpha=4.0,
                    beta=2.0,
                ),
                FeaturePosterior(
                    clinic_id=patient.clinic_id,
                    actor_role="all",
                    feature="medication",
                    alpha=4.0,
                    beta=2.0,
                ),
            ]
        )
        entry = create_entry(
            session,
            actor=actor,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Whitespace and learning contract",
            content="   Medication increased. Follow-up pending.",
            visibility="internal",
            trust_state="clinician_confirmed",
            source_uri="session://whitespace-learning",
        )
        generated = generate_highlights_for_entry(session, entry=entry)
        assert len(generated) == 2
        assert [item.confidence for item in generated] == [0.98, 0.98]
        assert [item.status for item in generated] == ["accepted", "accepted"]
        assert generated[0].adaptive_score == 0.25
        assert generated[0].rank_score == round(generated[0].base_score + 0.25, 4)
        first_span = session.get(ProvenanceSpan, generated[0].provenance_span_id)
        assert first_span is not None
        assert (first_span.start_offset, first_span.end_offset, first_span.quote) == (
            3,
            24,
            "Medication increased.",
        )
        repeated = generate_highlights_for_entry(session, entry=entry)
        assert [item.id for item in repeated] == [item.id for item in generated]

        same_offsets = create_entry(
            session,
            actor=actor,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Same offsets, different source",
            content="Medication increased.",
            visibility="internal",
            trust_state="clinician_confirmed",
            source_uri="session://same-offsets",
        )
        same_generated = generate_highlights_for_entry(session, entry=same_offsets)
        same_span = session.get(ProvenanceSpan, same_generated[0].provenance_span_id)
        assert same_span is not None
        assert same_span.source_entry_id == same_offsets.id
        assert same_span.source_version_id == same_offsets.current_version_id

        boundary_entry = create_entry(
            session,
            actor=actor,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Exact boundary identity",
            content="Medication increased.",
            visibility="internal",
            trust_state="clinician_confirmed",
            source_uri="session://boundary-identity",
        )
        boundary_version = current_version(session, boundary_entry)
        create_span(
            session,
            entry=boundary_entry,
            version=boundary_version,
            start_offset=0,
            end_offset=5,
        )
        create_span(
            session,
            entry=boundary_entry,
            version=boundary_version,
            start_offset=5,
            end_offset=21,
        )
        exact = generate_highlights_for_entry(session, entry=boundary_entry)
        exact_span = session.get(ProvenanceSpan, exact[0].provenance_span_id)
        assert exact_span is not None
        assert exact_span.source_entry_id == boundary_entry.id
        assert exact_span.source_version_id == boundary_entry.current_version_id
        assert (exact_span.start_offset, exact_span.end_offset, exact_span.quote) == (
            0,
            21,
            "Medication increased.",
        )

        blank_prefix_entry = create_entry(
            session,
            actor=actor,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Blank sentence resilience",
            content="   . Medication increased.",
            visibility="internal",
            trust_state="clinician_confirmed",
            source_uri="session://blank-sentence",
        )
        blank_prefix = generate_highlights_for_entry(session, entry=blank_prefix_entry)
        assert len(blank_prefix) == 1
        blank_span = session.get(ProvenanceSpan, blank_prefix[0].provenance_span_id)
        assert blank_span is not None
        assert (blank_span.start_offset, blank_span.quote) == (5, "Medication increased.")


def test_rank_scores_are_persisted_at_the_documented_four_decimal_precision(
    app, identities, patient_id, monkeypatch
):
    monkeypatch.setattr(
        importance_module,
        "base_score",
        lambda *args, **kwargs: (1.23456, {"precision_fixture": True}),
    )
    monkeypatch.setattr(
        importance_module,
        "adaptive_score",
        lambda *args, **kwargs: 0.00005,
    )
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        patient = session.get(Patient, patient_id)
        assert actor is not None and patient is not None
        entry = create_entry(
            session,
            actor=actor,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Rank precision contract",
            content="Medication increased.",
            visibility="internal",
            trust_state="clinician_confirmed",
            source_uri="session://rank-precision",
        )
        generated = generate_highlights_for_entry(session, entry=entry)
        assert len(generated) == 1
        assert generated[0].rank_score == 1.2346

        generated[0].rank_score = 0.0
        refresh_adaptive_scores(session, patient.clinic_id, "clinician")
        assert generated[0].adaptive_score == 0.00005
        assert generated[0].rank_score == 1.2346


def test_feedback_accepts_staff_full_propensity_and_accumulates_observations(
    app, identities, patient_id
):
    with app.state.database.session() as session:
        staff = session.get(User, identities["staff"])
        patient_actor = session.get(User, identities["patient"])
        highlight = session.scalar(select(Highlight).where(Highlight.patient_id == patient_id))
        assert staff is not None and patient_actor is not None and highlight is not None
        with pytest.raises(ValueError) as error:
            record_feedback(
                session,
                actor=patient_actor,
                highlight=highlight,
                action="accept",
                display_propensity=1.0,
            )
        assert error.value.args == ("Only staff and clinicians can train importance ranking",)

        first = record_feedback(
            session,
            actor=staff,
            highlight=highlight,
            action="accept",
            display_propensity=1.0,
        )
        second = record_feedback(
            session,
            actor=staff,
            highlight=highlight,
            action="accept",
            display_propensity=1.0,
        )
        assert first.display_propensity == second.display_propensity == 1.0
        posteriors = list(
            session.scalars(
                select(FeaturePosterior).where(
                    FeaturePosterior.clinic_id == staff.clinic_id,
                    FeaturePosterior.actor_role.in_(["staff", "all"]),
                    FeaturePosterior.feature.in_(highlight.entity_tags),
                )
            )
        )
        assert posteriors
        assert all(
            (item.alpha, item.beta, item.observations) == (4.0, 2.0, 2) for item in posteriors
        )


def test_ranking_and_glance_are_patient_scoped_bounded_ordered_and_grouped(
    app, identities, patient_id
):
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        other_actor = session.get(User, identities["other_clinician"])
        template = session.scalar(select(Highlight).where(Highlight.patient_id == patient_id))
        assert actor is not None and other_actor is not None and template is not None

        for item in session.scalars(select(Highlight).where(Highlight.patient_id == patient_id)):
            item.status = "rejected"

        def add_highlight(*, title: str, risk: str, patient: str, clinic: str) -> None:
            session.add(
                Highlight(
                    clinic_id=clinic,
                    patient_id=patient,
                    provenance_span_id=template.provenance_span_id,
                    title=title,
                    risk_level=risk,
                    risk_reason="Exact ranking fixture",
                    entity_tags=["medication"] if risk == "high" else ["follow_up"],
                    confidence=0.98,
                    trust_state="clinician_confirmed",
                    status="accepted",
                    base_score=5.0,
                    adaptive_score=0.0,
                    rank_score=5.0,
                    score_factors={"risk": 5.0},
                    policy_version=POLICY_VERSION,
                    created_at=now,
                )
            )

        add_highlight(
            title="Foreign critical",
            risk="critical",
            patient=OTHER_PATIENT_ID,
            clinic=other_actor.clinic_id,
        )
        add_highlight(
            title="Target high",
            risk="high",
            patient=patient_id,
            clinic=actor.clinic_id,
        )
        add_highlight(
            title="Target watch",
            risk="medium",
            patient=patient_id,
            clinic=actor.clinic_id,
        )
        for index in range(6):
            add_highlight(
                title=f"Target context {index}",
                risk="low",
                patient=patient_id,
                clinic=actor.clinic_id,
            )
        session.flush()
        ranked = ranked_highlights(session, patient_id)
        assert len(ranked) == 6
        assert all(item.patient_id == patient_id for item in ranked)

        for task in session.scalars(select(CareTask).where(CareTask.patient_id == patient_id)):
            task.status = "completed"
        for days in (4, 1, 3, 2):
            session.add(
                CareTask(
                    clinic_id=actor.clinic_id,
                    patient_id=patient_id,
                    title=f"Ordered task {days}",
                    status="open",
                    urgency="routine",
                    assigned_to=actor.id,
                    due_at=now + timedelta(days=days),
                    created_by=actor.id,
                )
            )
        session.add_all(
            [
                CareTask(
                    clinic_id=actor.clinic_id,
                    patient_id=patient_id,
                    title="Closed target task",
                    status="completed",
                    urgency="routine",
                    assigned_to=actor.id,
                    due_at=now,
                    created_by=actor.id,
                ),
                CareTask(
                    clinic_id=other_actor.clinic_id,
                    patient_id=OTHER_PATIENT_ID,
                    title="Foreign open task",
                    status="open",
                    urgency="high",
                    assigned_to=other_actor.id,
                    due_at=now,
                    created_by=other_actor.id,
                ),
            ]
        )
        session.flush()
        groups = build_glance_projection(session, patient_id)["groups"]
        assert [item["title"] for item in groups["act_now"]] == ["Target high"]
        assert [item["title"] for item in groups["watch"]][:1] == ["Target watch"]
        assert [item["title"] for item in groups["awaiting"]] == [
            "Ordered task 1",
            "Ordered task 2",
            "Ordered task 3",
        ]
