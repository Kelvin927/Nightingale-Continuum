from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.care import current_version
from app.constants import POLICY_VERSION
from app.models import (
    AuditEvent,
    CareTask,
    Conflict,
    Entry,
    Highlight,
    Patient,
    ProvenanceSpan,
    User,
)
from app.provenance import create_span
from app.review import _intent_matches, build_evidence_review, classify_review_intent
from app.seed import OTHER_PATIENT_ID

from .conftest import auth


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("MEDICATION", "medication"),
        ("medicine", "medication"),
        ("dose", "medication"),
        ("drug", "medication"),
        ("change", "change"),
        ("changed", "change"),
        ("different", "change"),
        ("since", "change"),
        ("action", "action"),
        ("next", "action"),
        ("pending", "action"),
        ("await", "action"),
        ("follow", "action"),
        ("risk", "safety"),
        ("safety", "safety"),
        ("urgent", "safety"),
        ("allergy", "safety"),
        ("summary", "overview"),
    ],
)
def test_review_intent_classification_is_small_and_deterministic(term, expected):
    assert classify_review_intent(f"  Please review {term}.  ") == expected


@pytest.mark.parametrize(
    ("intent", "tags", "risk_level", "expected"),
    [
        ("medication", ["medication"], "low", True),
        ("medication", ["dose_change"], "low", True),
        ("medication", ["follow_up"], "low", False),
        ("change", ["allergy"], "low", True),
        ("change", ["dose_change"], "low", True),
        ("change", ["symptom_change"], "low", True),
        ("change", ["follow_up"], "low", True),
        ("change", ["medication"], "low", False),
        ("action", ["follow_up"], "low", True),
        ("action", ["medication"], "low", False),
        ("safety", [], "critical", True),
        ("safety", [], "high", True),
        ("safety", [], "medium", False),
        ("overview", [], "low", True),
    ],
)
def test_review_intent_matching_contract(intent, tags, risk_level, expected):
    highlight = SimpleNamespace(entity_tags=tags, risk_level=risk_level)
    assert _intent_matches(intent, highlight) is expected


def test_evidence_review_separates_claims_actions_conflicts_and_abstention(
    app, identities, patient_id
):
    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        other_clinician = session.get(User, identities["other_clinician"])
        other_patient = session.get(Patient, OTHER_PATIENT_ID)
        assert clinician is not None and other_clinician is not None and other_patient is not None

        source_task = session.scalar(
            select(CareTask).where(
                CareTask.clinic_id == clinician.clinic_id,
                CareTask.patient_id == patient_id,
                CareTask.status == "open",
            )
        )
        source_conflict = session.scalar(
            select(Conflict).where(
                Conflict.clinic_id == clinician.clinic_id,
                Conflict.patient_id == patient_id,
                Conflict.status == "open",
            )
        )
        source_highlight = session.scalar(
            select(Highlight).where(
                Highlight.clinic_id == clinician.clinic_id,
                Highlight.patient_id == patient_id,
            )
        )
        foreign_entry = session.scalar(select(Entry).where(Entry.patient_id == other_patient.id))
        assert (
            source_task is not None
            and source_conflict is not None
            and source_highlight is not None
            and foreign_entry is not None
        )
        source_span = session.get(ProvenanceSpan, source_highlight.provenance_span_id)
        assert source_span is not None

        for highlight, span in session.execute(
            select(Highlight, ProvenanceSpan)
            .join(ProvenanceSpan)
            .where(
                Highlight.clinic_id == clinician.clinic_id,
                Highlight.patient_id == patient_id,
            )
        ):
            if span.quote.startswith("Obtain renal function"):
                highlight.created_at = datetime(2026, 2, 6, 10, 11, tzinfo=UTC)

        foreign_version = current_version(session, foreign_entry)
        foreign_span = create_span(
            session,
            entry=foreign_entry,
            version=foreign_version,
            start_offset=0,
            end_offset=len(foreign_version.content),
        )
        wrong_clinic_span = ProvenanceSpan(
            clinic_id=other_patient.clinic_id,
            patient_id=patient_id,
            source_entry_id=source_span.source_entry_id,
            source_version_id=source_span.source_version_id,
            start_offset=source_span.start_offset,
            end_offset=source_span.end_offset,
            quote=source_span.quote,
            source_content_hash=source_span.source_content_hash,
            source_kind=source_span.source_kind,
            source_uri=source_span.source_uri,
        )
        wrong_patient_span = ProvenanceSpan(
            clinic_id=clinician.clinic_id,
            patient_id=other_patient.id,
            source_entry_id=source_span.source_entry_id,
            source_version_id=source_span.source_version_id,
            start_offset=source_span.start_offset,
            end_offset=source_span.end_offset,
            quote=source_span.quote,
            source_content_hash=source_span.source_content_hash,
            source_kind=source_span.source_kind,
            source_uri=source_span.source_uri,
        )
        session.add_all([wrong_clinic_span, wrong_patient_span])
        session.flush()

        def isolation_highlight(
            *, title: str, clinic: str, patient: str, span_id: str, rank: float
        ) -> Highlight:
            return Highlight(
                clinic_id=clinic,
                patient_id=patient,
                provenance_span_id=span_id,
                title=title,
                risk_level="critical",
                risk_reason="Deliberate tenant-isolation fixture",
                entity_tags=["medication"],
                evidence_support=1.0,
                trust_state="clinician_confirmed",
                status="accepted",
                base_score=rank,
                adaptive_score=0.0,
                rank_score=rank,
                score_factors={"fixture": True},
                policy_version=POLICY_VERSION,
            )

        session.add_all(
            [
                isolation_highlight(
                    title="Mismatched provenance must not surface",
                    clinic=clinician.clinic_id,
                    patient=patient_id,
                    span_id=foreign_span.id,
                    rank=100.0,
                ),
                isolation_highlight(
                    title="Foreign highlight must not surface",
                    clinic=other_patient.clinic_id,
                    patient=other_patient.id,
                    span_id=foreign_span.id,
                    rank=101.0,
                ),
                isolation_highlight(
                    title="Wrong highlight clinic must not surface",
                    clinic=other_patient.clinic_id,
                    patient=patient_id,
                    span_id=source_span.id,
                    rank=102.0,
                ),
                isolation_highlight(
                    title="Wrong highlight patient must not surface",
                    clinic=clinician.clinic_id,
                    patient=other_patient.id,
                    span_id=source_span.id,
                    rank=103.0,
                ),
                isolation_highlight(
                    title="Wrong provenance clinic must not surface",
                    clinic=clinician.clinic_id,
                    patient=patient_id,
                    span_id=wrong_clinic_span.id,
                    rank=104.0,
                ),
                isolation_highlight(
                    title="Wrong provenance patient must not surface",
                    clinic=clinician.clinic_id,
                    patient=patient_id,
                    span_id=wrong_patient_span.id,
                    rank=105.0,
                ),
                CareTask(
                    clinic_id=clinician.clinic_id,
                    patient_id=patient_id,
                    title="First ordered review task",
                    status="open",
                    urgency="critical",
                    assigned_to=clinician.id,
                    due_at=datetime(2026, 2, 7, 10, tzinfo=UTC),
                    created_by=clinician.id,
                ),
                CareTask(
                    clinic_id=clinician.clinic_id,
                    patient_id=patient_id,
                    title="Third ordered review task",
                    status="open",
                    urgency="routine",
                    assigned_to=None,
                    due_at=datetime(2026, 2, 7, 14, tzinfo=UTC),
                    created_by=clinician.id,
                ),
                CareTask(
                    clinic_id=clinician.clinic_id,
                    patient_id=patient_id,
                    title="Fourth task beyond the response bound",
                    status="open",
                    urgency="routine",
                    assigned_to=clinician.id,
                    due_at=datetime(2026, 2, 7, 16, tzinfo=UTC),
                    created_by=clinician.id,
                ),
                CareTask(
                    clinic_id=clinician.clinic_id,
                    patient_id=patient_id,
                    title="Closed task must not surface",
                    status="completed",
                    urgency="critical",
                    assigned_to=clinician.id,
                    due_at=datetime(2026, 2, 1, 9, tzinfo=UTC),
                    created_by=clinician.id,
                ),
                CareTask(
                    clinic_id=other_patient.clinic_id,
                    patient_id=other_patient.id,
                    title="Foreign task must not surface",
                    status="open",
                    urgency="critical",
                    assigned_to=other_clinician.id,
                    due_at=datetime(2026, 2, 1, 8, tzinfo=UTC),
                    created_by=other_clinician.id,
                ),
                CareTask(
                    clinic_id=other_patient.clinic_id,
                    patient_id=patient_id,
                    title="Wrong task clinic must not surface",
                    status="open",
                    urgency="critical",
                    assigned_to=other_clinician.id,
                    due_at=datetime(2026, 2, 1, 7, 30, tzinfo=UTC),
                    created_by=other_clinician.id,
                ),
                CareTask(
                    clinic_id=clinician.clinic_id,
                    patient_id=other_patient.id,
                    title="Wrong task patient must not surface",
                    status="open",
                    urgency="critical",
                    assigned_to=clinician.id,
                    due_at=datetime(2026, 2, 1, 7, tzinfo=UTC),
                    created_by=clinician.id,
                ),
                Conflict(
                    clinic_id=clinician.clinic_id,
                    patient_id=patient_id,
                    left_version_id=source_conflict.left_version_id,
                    right_version_id=source_conflict.right_version_id,
                    conflict_type="ordered_fixture",
                    summary="Newer open conflict",
                    status="open",
                    created_at=datetime(2026, 2, 6, 11, tzinfo=UTC),
                ),
                Conflict(
                    clinic_id=clinician.clinic_id,
                    patient_id=patient_id,
                    left_version_id=source_conflict.left_version_id,
                    right_version_id=source_conflict.right_version_id,
                    conflict_type="closed_fixture",
                    summary="Closed conflict must not surface",
                    status="resolved",
                    created_at=datetime(2026, 2, 6, 12, tzinfo=UTC),
                ),
                Conflict(
                    clinic_id=other_patient.clinic_id,
                    patient_id=other_patient.id,
                    left_version_id=source_conflict.left_version_id,
                    right_version_id=source_conflict.right_version_id,
                    conflict_type="foreign_fixture",
                    summary="Foreign conflict must not surface",
                    status="open",
                    created_at=datetime(2026, 2, 6, 13, tzinfo=UTC),
                ),
                Conflict(
                    clinic_id=other_patient.clinic_id,
                    patient_id=patient_id,
                    left_version_id=source_conflict.left_version_id,
                    right_version_id=source_conflict.right_version_id,
                    conflict_type="wrong_clinic_fixture",
                    summary="Wrong conflict clinic must not surface",
                    status="open",
                    created_at=datetime(2026, 2, 6, 14, tzinfo=UTC),
                ),
                Conflict(
                    clinic_id=clinician.clinic_id,
                    patient_id=other_patient.id,
                    left_version_id=source_conflict.left_version_id,
                    right_version_id=source_conflict.right_version_id,
                    conflict_type="wrong_patient_fixture",
                    summary="Wrong conflict patient must not surface",
                    status="open",
                    created_at=datetime(2026, 2, 6, 15, tzinfo=UTC),
                ),
            ]
        )
        session.flush()

        overview = build_evidence_review(
            session,
            clinic_id=clinician.clinic_id,
            patient_id=patient_id,
            question="Summarize the record",
        )
        assert overview.intent == "overview"
        assert overview.answer_state == "supported"
        assert overview.summary == "Found 4 source-bound signals for this overview review."
        assert [
            (
                claim.text,
                claim.risk_level,
                claim.risk_reason,
                claim.trust_state,
                claim.evidence_support,
                claim.quote,
            )
            for claim in overview.claims
        ] == [
            (
                "Allergy safety signal",
                "critical",
                "Allergy or severe reaction language requires prominent review",
                "clinician_confirmed",
                0.95,
                "Allergy: penicillin caused facial swelling in childhood.",
            ),
            (
                "Medication detail to reconcile",
                "high",
                "Medication or dose information is a known high-risk scribe error class",
                "clinician_confirmed",
                0.95,
                "Obtain renal function lab before deciding on the medication dose.",
            ),
            (
                "Medication detail to reconcile",
                "high",
                "Medication or dose information is a known high-risk scribe error class",
                "clinician_confirmed",
                0.95,
                "Dizziness may be temporally associated with the recent lisinopril dose increase; "
                "causality is not established.",
            ),
            (
                "Medication detail to reconcile",
                "high",
                "Medication or dose information is a known high-risk scribe error class",
                "ai_proposed",
                0.65,
                "Patient reports dizziness since the lisinopril dose changed from 10 mg to 20 mg.",
            ),
        ]
        assert [claim.evidence_support_band for claim in overview.claims] == [
            "high",
            "high",
            "high",
            "medium",
        ]
        assert {claim.evidence_support_interpretation for claim in overview.claims} == {
            "Policy-defined evidence support; not a calibrated probability of clinical correctness."
        }
        assert all(claim.provenance_span_id and claim.source_entry_id for claim in overview.claims)
        assert [
            (action.title, action.urgency, action.assigned_to, action.due_at)
            for action in overview.open_actions
        ] == [
            ("First ordered review task", "critical", clinician.id, "2026-02-07T10:00:00"),
            (
                "Place renal function lab order",
                "high",
                source_task.assigned_to,
                "2026-02-07T12:00:00",
            ),
            ("Third ordered review task", "routine", None, "2026-02-07T14:00:00"),
        ]
        assert overview.open_actions[0].source_entry_id is None
        assert overview.open_actions[1].source_entry_id == source_task.source_entry_id
        assert overview.conflicts == (
            "Newer open conflict",
            "Allergy status mismatch: a no-known-allergy statement conflicts with "
            "a recorded reaction to penicillin.",
            "AI session asks whether to continue 20 mg; clinician plan defers the decision "
            "pending labs.",
        )
        assert overview.abstention_reason is None
        assert overview.provider == "local-evidence-reviewer-v1"
        assert overview.to_dict()["claims"][0]["provenance_span_id"]
        assert overview.safety_notice == (
            "This review organizes recorded evidence; it does not diagnose, prescribe, or "
            "confirm clinical truth. A qualified clinician must review every action."
        )

        medication = build_evidence_review(
            session,
            clinic_id=clinician.clinic_id,
            patient_id=patient_id,
            question="Which medicine or dose needs review?",
        )
        assert medication.intent == "medication"
        assert medication.summary == "Found 4 source-bound signals for this medication review."
        assert [claim.quote for claim in medication.claims] == [
            "Obtain renal function lab before deciding on the medication dose.",
            "Dizziness may be temporally associated with the recent lisinopril dose increase; "
            "causality is not established.",
            "Patient reports dizziness since the lisinopril dose changed from 10 mg to 20 mg.",
            "She is awaiting a nurse follow-up and asks whether the new dose should continue.",
        ]

        changed = build_evidence_review(
            session,
            clinic_id=clinician.clinic_id,
            patient_id=patient_id,
            question="What is different since the previous visit?",
        )
        safety = build_evidence_review(
            session,
            clinic_id=clinician.clinic_id,
            patient_id=patient_id,
            question="What safety risk is urgent?",
        )
        assert changed.intent == "change" and changed.claims
        assert safety.intent == "safety" and safety.claims

        first_medication_span = medication.claims[0].provenance_span_id
        for highlight in session.scalars(
            select(Highlight).where(Highlight.patient_id == patient_id)
        ):
            if "medication" in highlight.entity_tags and (
                highlight.provenance_span_id != first_medication_span
            ):
                highlight.status = "rejected"
        session.flush()
        singular = build_evidence_review(
            session,
            clinic_id=clinician.clinic_id,
            patient_id=patient_id,
            question="Which medication is recorded?",
        )
        assert singular.summary == "Found 1 source-bound signal for this medication review."
        assert len(singular.claims) == 1

        follow_up_highlights = [
            highlight
            for highlight in session.scalars(
                select(Highlight).where(Highlight.patient_id == patient_id)
            )
            if "follow_up" in highlight.entity_tags
        ]
        assert follow_up_highlights
        for highlight in follow_up_highlights:
            highlight.status = "rejected"
        session.flush()
        workflow = build_evidence_review(
            session,
            clinic_id=clinician.clinic_id,
            patient_id=patient_id,
            question="What action is awaiting follow-up?",
        )
        assert workflow.answer_state == "workflow_only"
        assert workflow.summary == "Found 3 open workflow actions."
        assert workflow.claims == ()
        assert workflow.open_actions[0].due_at is not None
        assert workflow.abstention_reason == (
            "No matching clinical claim was asserted; only open workflow data is shown."
        )

        other_action = build_evidence_review(
            session,
            clinic_id=other_patient.clinic_id,
            patient_id=other_patient.id,
            question="What next action is pending?",
        )
        assert other_action.answer_state == "workflow_only"
        assert other_action.summary == "Found 1 open workflow action."
        assert other_action.open_actions[0].title == "Foreign task must not surface"

        foreign_highlight = session.scalar(
            select(Highlight).where(Highlight.title == "Foreign highlight must not surface")
        )
        assert foreign_highlight is not None
        foreign_highlight.status = "rejected"
        session.flush()
        insufficient = build_evidence_review(
            session,
            clinic_id=other_patient.clinic_id,
            patient_id=other_patient.id,
            question="Which medication dose is supported?",
        )
        assert insufficient.answer_state == "insufficient_evidence"
        assert insufficient.summary == (
            "The available record does not support a source-bound answer to this question."
        )
        assert insufficient.claims == ()
        assert insufficient.abstention_reason == (
            "Review the timeline or add verified evidence before acting."
        )


def test_review_api_is_role_scoped_source_bound_and_logs_metadata_only(
    client, app, identities, patient_id
):
    question = "Which medication dose needs review?"
    response = client.post(
        "/api/v1/review/query",
        headers=auth(identities["clinician"]),
        json={"patient_id": patient_id, "question": question},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_state"] == "supported"
    assert payload["intent"] == "medication"
    assert payload["claims"]

    for claim in payload["claims"]:
        resolved = client.get(
            f"/api/v1/provenance/{claim['provenance_span_id']}/resolve",
            headers=auth(identities["clinician"]),
        )
        assert resolved.status_code == 200
        assert resolved.json()["source_entry_id"] == claim["source_entry_id"]
        assert resolved.json()["quote"] == claim["quote"]

    with app.state.database.session() as session:
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "evidence_review.generated")
        )
        assert event is not None
        assert event.event_metadata == {
            "intent": "medication",
            "answer_state": "supported",
            "claim_count": len(payload["claims"]),
            "question_hash": sha256(question.encode("utf-8")).hexdigest(),
            "provider": "local-evidence-reviewer-v1",
        }
        assert question not in str(event.event_metadata)

    patient_denied = client.post(
        "/api/v1/review/query",
        headers=auth(identities["patient"]),
        json={"patient_id": patient_id, "question": question},
    )
    assert patient_denied.status_code == 404

    cross_clinic = client.post(
        "/api/v1/review/query",
        headers=auth(identities["clinician"]),
        json={"patient_id": OTHER_PATIENT_ID, "question": question},
    )
    assert cross_clinic.status_code == 404

    invalid = client.post(
        "/api/v1/review/query",
        headers=auth(identities["clinician"]),
        json={"patient_id": patient_id, "question": "x"},
    )
    assert invalid.status_code == 422
