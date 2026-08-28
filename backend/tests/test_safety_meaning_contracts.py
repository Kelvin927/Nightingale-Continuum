from __future__ import annotations

from collections import Counter

import pytest
from sqlalchemy import select

from app import scribe as scribe_module
from app.care import create_entry, edit_entry
from app.conflicts import (
    _allergy_assertions,
    _already_open,
    _medication_doses,
    detect_structured_conflicts,
)
from app.constants import POLICY_VERSION
from app.evaluation import evaluate_shadow_policy
from app.importance import (
    evidence_support_band,
    evidence_support_score,
    generate_highlights_for_entry,
    ranked_highlights,
)
from app.models import Conflict, ImportanceFeedback, Patient, User
from app.redaction import (
    Finding,
    RedactionReceipt,
    RedactionResult,
    _clinical_anchor_signature,
    redact_text,
)
from app.review import build_evidence_review

from .conftest import auth, workspace


def test_evidence_support_is_a_bounded_policy_contract_not_model_self_report() -> None:
    assert evidence_support_score("ai_proposed") == 0.65
    assert evidence_support_score("human_authored") == 0.75
    assert evidence_support_score("staff_verified") == 0.85
    assert evidence_support_score("clinician_confirmed") == 0.95
    assert evidence_support_score("superseded") == 0.0
    with pytest.raises(ValueError, match="Unsupported trust state"):
        evidence_support_score("model_says_certain")

    assert evidence_support_band(0.0) == "low"
    assert evidence_support_band(0.59) == "low"
    assert evidence_support_band(0.6) == "medium"
    assert evidence_support_band(0.849) == "medium"
    assert evidence_support_band(0.85) == "high"
    assert evidence_support_band(1.0) == "high"
    with pytest.raises(ValueError) as below_range:
        evidence_support_band(-0.01)
    assert below_range.value.args == ("Evidence support score must be in [0, 1]",)
    with pytest.raises(ValueError) as above_range:
        evidence_support_band(1.01)
    assert above_range.value.args == ("Evidence support score must be in [0, 1]",)


def test_only_current_version_highlights_remain_rankable(app, identities, patient_id) -> None:
    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        patient = session.get(Patient, patient_id)
        assert clinician is not None and patient is not None
        entry = create_entry(
            session,
            actor=clinician,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Current-version evidence contract",
            content="Lisinopril 10 mg requires medication review.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        old_highlights = generate_highlights_for_entry(session, entry=entry)
        assert old_highlights
        edit_entry(
            session,
            actor=clinician,
            entry=entry,
            content="Lisinopril 20 mg requires medication review.",
            expected_version=1,
            reason="Correct the current dose",
        )
        new_highlights = generate_highlights_for_entry(session, entry=entry)
        assert new_highlights

        ranked_ids = {item.id for item in ranked_highlights(session, patient.id)}
        assert {item.id for item in new_highlights} <= ranked_ids
        assert not ({item.id for item in old_highlights} & ranked_ids)
        review = build_evidence_review(
            session,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            question="Review medication evidence",
        )
        review_span_ids = {claim.provenance_span_id for claim in review.claims}
        assert {item.provenance_span_id for item in new_highlights} <= review_span_ids
        assert not ({item.provenance_span_id for item in old_highlights} & review_span_ids)


def test_patient_release_requires_clinician_confirmation(
    client, app, identities, patient_id
) -> None:
    staff_release = client.post(
        f"/api/v1/patients/{patient_id}/entries",
        headers=auth(identities["staff"]),
        json={
            "entry_type": "patient_instruction",
            "title": "Unconfirmed instruction",
            "content": "Change the medication tomorrow.",
            "visibility": "patient",
        },
    )
    assert staff_release.status_code == 403
    assert staff_release.json()["detail"]["code"] == "clinician_confirmation_required"

    wrong_clinical_type = client.post(
        f"/api/v1/patients/{patient_id}/entries",
        headers=auth(identities["clinician"]),
        json={
            "entry_type": "clinician_note",
            "title": "Internal note cannot be released",
            "content": "Internal differential only.",
            "visibility": "patient",
        },
    )
    assert wrong_clinical_type.status_code == 403
    assert wrong_clinical_type.json()["detail"]["code"] == "patient_entry_type_required"

    approved = client.post(
        f"/api/v1/patients/{patient_id}/entries",
        headers=auth(identities["clinician"]),
        json={
            "entry_type": "patient_summary",
            "title": "Clinician-approved summary",
            "content": "Continue the agreed plan and contact the care team if symptoms worsen.",
            "visibility": "patient",
        },
    )
    assert approved.status_code == 201
    approved_id = approved.json()["id"]

    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        patient = session.get(Patient, patient_id)
        assert clinician is not None and patient is not None
        unconfirmed = create_entry(
            session,
            actor=clinician,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="clinician",
            entry_type="patient_instruction",
            title="Unsafe fixture",
            content="This fixture must remain hidden.",
            visibility="patient",
            trust_state="ai_proposed",
        )
        unconfirmed_id = unconfirmed.id
        session.commit()

    patient_view = workspace(client, identities["patient"], patient_id)
    visible_ids = {item["id"] for item in patient_view["entries"]}
    assert approved_id in visible_ids
    assert unconfirmed_id not in visible_ids
    direct_access = client.get(
        f"/api/v1/entries/{unconfirmed_id}/versions",
        headers=auth(identities["patient"]),
    )
    assert direct_access.status_code == 404


def test_feedback_logging_is_honest_about_deterministic_exposure(
    client, app, identities, patient_id
) -> None:
    projection = client.get(
        f"/api/v1/patients/{patient_id}/glance",
        headers=auth(identities["clinician"]),
    ).json()
    highlight_id = projection["groups"]["act_now"][0]["id"]
    response = client.post(
        f"/api/v1/highlights/{highlight_id}/feedback",
        headers=auth(identities["clinician"]),
        json={"action": "accept", "display_propensity": 0.02},
    )
    assert response.status_code == 200

    with app.state.database.session() as session:
        record = session.scalar(
            select(ImportanceFeedback).where(ImportanceFeedback.highlight_id == highlight_id)
        )
        clinician = session.get(User, identities["clinician"])
        assert record is not None and clinician is not None
        assert record.display_propensity == 1.0
        session.add(
            ImportanceFeedback(
                clinic_id=clinician.clinic_id,
                highlight_id=highlight_id,
                actor_id=clinician.id,
                action="accept",
                reward=1.0,
                policy_version=POLICY_VERSION,
                display_propensity=0.999,
                context={"base_score": 8.0, "risk_level": "critical"},
            )
        )
        session.flush()
        evaluation = evaluate_shadow_policy(session, clinician.clinic_id)
        assert evaluation.exposure_bias_warning is True
        assert evaluation.overlap_warning is True
        assert evaluation.status == "exploratory"


def test_redaction_receipt_proves_privacy_and_clinical_anchor_fidelity() -> None:
    assert _clinical_anchor_signature("LISINOPRIL 20    mg and dose") == Counter(
        {"lisinopril": 1, "20mg": 1, "dose": 1}
    )
    result = redact_text(
        "Dr Jane Lim prescribed lisinopril 20 mg after medication review.",
        known_names=["Jane Lim"],
    )
    assert "Jane Lim" not in result.text
    assert "lisinopril 20 mg" in result.text
    assert result.receipt.clinical_anchor_count == 3
    assert result.receipt.clinical_anchors_preserved is True
    assert result.receipt.passed is True

    unsafe = redact_text(
        "Patient name: Lisinopril Dose reports 20 mg.",
        known_names=["Lisinopril Dose"],
    )
    assert unsafe.receipt.clinical_anchors_preserved is False
    assert unsafe.receipt.passed is False


def test_scribe_fails_closed_before_provider_when_redaction_fidelity_fails(
    client, app, identities, patient_id, monkeypatch
) -> None:
    failed = RedactionResult(
        text="Withheld",
        findings=(Finding("PERSON", 0, 4, 0.99),),
        receipt=RedactionReceipt(
            detector_version="forced-failure",
            entity_counts={"PERSON": 1},
            sanitized_sha256="0" * 64,
            clinical_anchor_count=2,
            clinical_anchors_preserved=False,
            passed=False,
        ),
    )
    monkeypatch.setattr(scribe_module, "redact_text", lambda *_args, **_kwargs: failed)
    provider = app.state.scribe_provider
    assert provider.last_received_text is None
    response = client.post(
        "/api/v1/scribe/ingest",
        headers=auth(identities["clinician"]),
        json={
            "patient_id": patient_id,
            "interaction_type": "doctor_consult",
            "transcript": "Synthetic transcript with lisinopril 20 mg for fidelity testing.",
            "source_uri": "session://redaction-fidelity-failure",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "redaction_fidelity_failed"
    assert provider.last_received_text is None


def _isolated_patient(session, clinician: User, suffix: str) -> Patient:
    patient = Patient(
        clinic_id=clinician.clinic_id,
        display_name=f"Safety Fixture {suffix}",
        initials="SF",
        synthetic_record_number=f"SYN-{suffix}",
        date_of_birth="1990-01-01",
        pronouns="they/them",
        synthetic=True,
    )
    session.add(patient)
    session.flush()
    return patient


def test_bounded_conflict_detector_finds_dose_and_allergy_mismatches_without_duplicates(
    app, identities
) -> None:
    assert _medication_doses("No supported medicine here.") == {}
    assert _medication_doses("Lisinopril 10 mg and 20 mg.") == {"lisinopril": {"10 mg", "20 mg"}}
    assert _medication_doses("Lisinopril 10\tmg. Metformin 500 mg!") == {
        "lisinopril": {"10 mg"},
        "metformin": {"500 mg"},
    }
    assert _allergy_assertions("Allergy: penicillin caused facial swelling.") == (
        {"penicillin"},
        False,
    )
    assert _allergy_assertions("Penicillin allergy.") == ({"penicillin"}, False)
    assert _allergy_assertions("Penicillin anaphylaxis.") == ({"penicillin"}, False)
    assert _allergy_assertions("Penicillin caused facial swelling.") == ({"penicillin"}, False)
    assert _allergy_assertions("Penicillin caused rash.") == ({"penicillin"}, False)
    assert _allergy_assertions("Penicillin was considered without a reaction statement.") == (
        set(),
        False,
    )
    assert _allergy_assertions("NKDA.") == (set(), True)

    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        assert clinician is not None
        dose_patient = _isolated_patient(session, clinician, "DOSE")
        dose_10 = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=dose_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Dose ten",
            content="Lisinopril 10 mg daily.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        assert detect_structured_conflicts(session, dose_10) == []
        dose_20 = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=dose_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Dose twenty",
            content="Lisinopril 20 mg daily.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        dose_conflicts = detect_structured_conflicts(session, dose_20)
        assert len(dose_conflicts) == 1
        assert dose_conflicts[0].conflict_type == "medication_dose_mismatch"
        assert dose_conflicts[0].summary == ("Dose mismatch for lisinopril: 20 mg versus 10 mg.")
        assert detect_structured_conflicts(session, dose_20) == []

        same_dose = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=dose_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Matching dose",
            content="Lisinopril 20 mg remains current.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        same_dose_conflicts = detect_structured_conflicts(session, same_dose)
        assert len(same_dose_conflicts) == 1
        assert "10 mg" in same_dose_conflicts[0].summary

        allergy_patient = _isolated_patient(session, clinician, "ALLERGY")
        positive = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=allergy_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Allergy present",
            content="Allergy: penicillin caused facial swelling.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        assert detect_structured_conflicts(session, positive) == []
        negative = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=allergy_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Allergy denied",
            content="NKDA.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        allergy_conflicts = detect_structured_conflicts(session, negative)
        assert len(allergy_conflicts) == 1
        assert allergy_conflicts[0].conflict_type == "allergy_status_mismatch"
        assert "penicillin" in allergy_conflicts[0].summary
        assert detect_structured_conflicts(session, negative) == []
        assert session.scalar(select(Conflict).where(Conflict.patient_id == allergy_patient.id))


def test_conflict_deduplication_requires_patient_type_status_and_unordered_version_pair(
    app, identities
) -> None:
    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        assert clinician is not None
        target = _isolated_patient(session, clinician, "DEDUP-TARGET")
        foreign = _isolated_patient(session, clinician, "DEDUP-FOREIGN")
        left = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=target.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Dedup left",
            content="Lisinopril 10 mg.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        right = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=target.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Dedup right",
            content="Lisinopril 20 mg.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        pair = (left.current_version_id, right.current_version_id)
        assert all(pair)

        def add_fixture(
            *, patient: str, kind: str, status: str, summary: str = "Deduplication scope fixture"
        ) -> None:
            session.add(
                Conflict(
                    clinic_id=clinician.clinic_id,
                    patient_id=patient,
                    left_version_id=pair[0],
                    right_version_id=pair[1],
                    conflict_type=kind,
                    summary=summary,
                    status=status,
                )
            )
            session.flush()

        add_fixture(patient=foreign.id, kind="medication_dose_mismatch", status="open")
        assert not _already_open(
            session,
            patient_id=target.id,
            conflict_type="medication_dose_mismatch",
            summary="Deduplication scope fixture",
            left_version_id=pair[0],
            right_version_id=pair[1],
        )
        add_fixture(patient=target.id, kind="allergy_status_mismatch", status="open")
        assert not _already_open(
            session,
            patient_id=target.id,
            conflict_type="medication_dose_mismatch",
            summary="Deduplication scope fixture",
            left_version_id=pair[0],
            right_version_id=pair[1],
        )
        add_fixture(patient=target.id, kind="medication_dose_mismatch", status="resolved")
        assert not _already_open(
            session,
            patient_id=target.id,
            conflict_type="medication_dose_mismatch",
            summary="Deduplication scope fixture",
            left_version_id=pair[0],
            right_version_id=pair[1],
        )
        add_fixture(
            patient=target.id,
            kind="medication_dose_mismatch",
            status="open",
            summary="Different medication conflict",
        )
        assert not _already_open(
            session,
            patient_id=target.id,
            conflict_type="medication_dose_mismatch",
            summary="Deduplication scope fixture",
            left_version_id=pair[0],
            right_version_id=pair[1],
        )
        add_fixture(patient=target.id, kind="medication_dose_mismatch", status="open")
        assert _already_open(
            session,
            patient_id=target.id,
            conflict_type="medication_dose_mismatch",
            summary="Deduplication scope fixture",
            left_version_id=pair[1],
            right_version_id=pair[0],
        )


def test_conflict_detector_continues_after_matches_duplicates_and_neutral_notes(
    app, identities
) -> None:
    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        other_clinician = session.get(User, identities["other_clinician"])
        assert clinician is not None and other_clinician is not None

        medication_patient = _isolated_patient(session, clinician, "MULTI-MED")
        create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=medication_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Two medication baseline",
            content="Lisinopril 10 mg. Metformin 500 mg.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        changed = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=medication_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="One medication changed",
            content="Lisinopril 10 mg. Metformin 1000 mg.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        changed_conflicts = detect_structured_conflicts(session, changed)
        assert [item.summary for item in changed_conflicts] == [
            "Dose mismatch for metformin: 1000 mg versus 500 mg."
        ]

        duplicate_patient = _isolated_patient(session, clinician, "MULTI-DUP")
        create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=duplicate_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Two mismatches baseline",
            content="Lisinopril 10 mg. Metformin 500 mg.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        two_changed = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=duplicate_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Two mismatches current",
            content="Lisinopril 20 mg. Metformin 1000 mg.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        initial = detect_structured_conflicts(session, two_changed)
        assert [item.conflict_type for item in initial] == [
            "medication_dose_mismatch",
            "medication_dose_mismatch",
        ]
        metformin_conflict = next(item for item in initial if "metformin" in item.summary)
        metformin_conflict.status = "resolved"
        session.flush()
        repeated = detect_structured_conflicts(session, two_changed)
        assert [item.summary for item in repeated] == [
            "Dose mismatch for metformin: 1000 mg versus 500 mg."
        ]

        multi_dose_patient = _isolated_patient(session, clinician, "MULTI-DOSE")
        create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=multi_dose_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Multiple prior doses",
            content="Lisinopril 5 mg and 15 mg.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        multi_dose = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=multi_dose_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Multiple current doses",
            content="Lisinopril 10 mg and 20 mg.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        assert [item.summary for item in detect_structured_conflicts(session, multi_dose)] == [
            "Dose mismatch for lisinopril: 10 mg, 20 mg versus 15 mg, 5 mg."
        ]

        allergy_patient = _isolated_patient(session, clinician, "MULTI-ALLERGY")
        create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=allergy_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Neutral note first",
            content="Routine follow-up documented.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=allergy_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Two allergies",
            content="Penicillin allergy and latex rash.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        denies = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=allergy_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Allergies denied",
            content="No known drug allergies.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        first_allergy = detect_structured_conflicts(session, denies)
        assert [item.summary for item in first_allergy] == [
            "Allergy status mismatch: a no-known-allergy statement conflicts with "
            "a recorded reaction to latex, penicillin."
        ]
        create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=allergy_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Second allergy source",
            content="Metformin caused anaphylaxis.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        second_allergy = detect_structured_conflicts(session, denies)
        assert [item.summary for item in second_allergy] == [
            "Allergy status mismatch: a no-known-allergy statement conflicts with "
            "a recorded reaction to metformin."
        ]

        scoped_patient = _isolated_patient(session, clinician, "CLINIC-SCOPE")
        create_entry(
            session,
            actor=other_clinician,
            clinic_id=other_clinician.clinic_id,
            patient_id=scoped_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Foreign clinic dose",
            content="Warfarin 1 mg.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        scoped = create_entry(
            session,
            actor=clinician,
            clinic_id=clinician.clinic_id,
            patient_id=scoped_patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Local clinic dose",
            content="Warfarin 5 mg.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        assert detect_structured_conflicts(session, scoped) == []
