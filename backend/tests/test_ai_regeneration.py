from __future__ import annotations

import pytest
from sqlalchemy import select

from app import main as main_module
from app import scribe as scribe_module
from app.care import create_entry
from app.models import (
    AuditEvent,
    CareTask,
    Conflict,
    Entry,
    Highlight,
    Patient,
    User,
)
from app.scribe import RedactionFidelityError, RegenerationError, regenerate_scribe

from .conftest import auth, entry_named, workspace


def _regeneration_payload(version: int = 1) -> dict:
    return {
        "expected_version": version,
        "transcript": (
            "Synthetic corrected consult: medication remains 20 mg and follow-up is pending."
        ),
        "source_uri": "session://synthetic/regeneration-review",
    }


def _ai_entry(client, identities, patient_id) -> dict:
    return entry_named(
        workspace(client, identities["clinician"], patient_id), "Pre-visit AI session"
    )


def test_regeneration_creates_only_a_new_proposal_and_preserves_human_state(
    client, app, identities, patient_id
) -> None:
    predecessor = _ai_entry(client, identities, patient_id)
    glance = client.get(
        f"/api/v1/patients/{patient_id}/glance",
        headers=auth(identities["clinician"]),
    ).json()
    highlight_id = glance["groups"]["act_now"][0]["id"]
    assert (
        client.post(
            f"/api/v1/highlights/{highlight_id}/feedback",
            headers=auth(identities["clinician"]),
            json={"action": "pin"},
        ).status_code
        == 200
    )

    conflict_id = workspace(client, identities["clinician"], patient_id)["conflicts"][0]["id"]
    assert (
        client.post(
            f"/api/v1/conflicts/{conflict_id}/resolve",
            headers=auth(identities["clinician"]),
            json={
                "decision": "escalate_unresolved",
                "rationale": "The two immutable assertions require external reconciliation.",
                "confirm_sources_reviewed": True,
            },
        ).status_code
        == 200
    )

    patient_instruction = entry_named(
        workspace(client, identities["clinician"], patient_id), "Your visit summary"
    )
    readiness = client.get(
        f"/api/v1/patients/{patient_id}/delivery-readiness",
        headers=auth(identities["clinician"]),
    ).json()
    contact_id = readiness["contacts"][0]["id"]
    assert (
        client.post(
            f"/api/v1/entries/{patient_instruction['id']}/deliveries",
            headers=auth(identities["clinician"]),
            json={
                "contact_id": contact_id,
                "expected_version": patient_instruction["current_version"],
                "idempotency_key": "regeneration-preservation-delivery",
                "confirm_clinical_review": True,
                "confirm_patient_identity": True,
                "confirm_medication_and_dose": True,
            },
        ).status_code
        == 201
    )

    started = client.post(
        f"/api/v1/patients/{patient_id}/captures",
        headers=auth(identities["clinician"]),
        json={"interaction_type": "doctor_consult"},
    ).json()
    segment = client.post(
        f"/api/v1/captures/{started['id']}/segments",
        headers=auth(identities["clinician"]),
        json={
            "chunk_id": "regeneration-signal-chunk",
            "sequence": 1,
            "start_ms": 120_000,
            "end_ms": 124_000,
            "speaker_label": "patient",
            "text": "Allergic to penicillin.",
            "language_spans": [
                {
                    "language_tag": "en-SG",
                    "start_offset": 0,
                    "end_offset": 23,
                    "confidence": 0.95,
                }
            ],
            "asr_confidence": 0.95,
            "audio_quality": 0.95,
            "correction_of_segment_id": None,
        },
    ).json()
    signal_id = segment["safety_signals"][0]["id"]
    assert (
        client.post(
            f"/api/v1/safety-signals/{signal_id}/review",
            headers=auth(identities["clinician"]),
            json={
                "decision": "confirm",
                "rationale": "Confirmed directly against the source interaction.",
            },
        ).status_code
        == 200
    )

    with app.state.database.session() as session:
        task = session.scalar(
            select(CareTask).where(CareTask.patient_id == patient_id, CareTask.status == "open")
        )
        assert task is not None
        task.status = "completed"
        completed_task_id = task.id
        human_before = {
            item.id: (item.current_version_id, item.current_version, item.trust_state)
            for item in session.scalars(
                select(Entry).where(Entry.patient_id == patient_id, Entry.owner_role != "system")
            )
        }
        session.commit()

    response = client.post(
        f"/api/v1/entries/{predecessor['id']}/regenerate",
        headers=auth(identities["clinician"]),
        json=_regeneration_payload(predecessor["current_version"]),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["entry_id"] != predecessor["id"]
    assert body["predecessor_entry_id"] == predecessor["id"]
    assert body["status"] == "new_ai_proposal_created"
    receipt = body["preservation_receipt"]
    assert receipt["unchanged"] is True
    assert len(receipt["protected_state_hash"]) == 64
    assert receipt["protected_highlight_count"] > 0
    assert receipt["completed_task_count"] == 1
    assert receipt["resolved_conflict_count"] == 1
    assert receipt["released_delivery_count"] == 1
    assert receipt["reviewed_signal_count"] == 1

    refreshed = workspace(client, identities["clinician"], patient_id)
    new_entry = next(item for item in refreshed["entries"] if item["id"] == body["entry_id"])
    assert new_entry["trust_state"] == "ai_proposed"
    assert new_entry["owner_role"] == "system"
    assert next(item for item in refreshed["entries"] if item["id"] == predecessor["id"])

    with app.state.database.session() as session:
        human_after = {
            item.id: (item.current_version_id, item.current_version, item.trust_state)
            for item in session.scalars(
                select(Entry).where(Entry.patient_id == patient_id, Entry.owner_role != "system")
            )
        }
        assert human_after == human_before
        assert session.get(Highlight, highlight_id).status == "pinned"
        completed_task = session.get(CareTask, completed_task_id)
        assert completed_task is not None and completed_task.status == "completed"
        assert session.get(Conflict, conflict_id).status == "escalated"
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "scribe.regenerated",
                AuditEvent.object_id == body["entry_id"],
            )
        )
        assert event is not None
        assert event.event_metadata["protected_state_hash"] == receipt["protected_state_hash"]


def test_regeneration_api_rejects_roles_wrong_layers_stale_versions_and_missing_system(
    client, app, identities, patient_id
) -> None:
    predecessor = _ai_entry(client, identities, patient_id)
    for actor in (identities["patient"], identities["admin"]):
        denied = client.post(
            f"/api/v1/entries/{predecessor['id']}/regenerate",
            headers=auth(actor),
            json=_regeneration_payload(),
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "regeneration_role_required"

    human = entry_named(
        workspace(client, identities["clinician"], patient_id), "Assessment and plan"
    )
    wrong_layer = client.post(
        f"/api/v1/entries/{human['id']}/regenerate",
        headers=auth(identities["clinician"]),
        json=_regeneration_payload(),
    )
    assert wrong_layer.status_code == 409
    assert wrong_layer.json()["detail"]["code"] == "proposal_layer_required"

    stale = client.post(
        f"/api/v1/entries/{predecessor['id']}/regenerate",
        headers=auth(identities["clinician"]),
        json=_regeneration_payload(99),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "regeneration_version_conflict"

    invalid_uri = client.post(
        f"/api/v1/entries/{predecessor['id']}/regenerate",
        headers=auth(identities["clinician"]),
        json={**_regeneration_payload(), "source_uri": "not-addressable"},
    )
    assert invalid_uri.status_code == 422

    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        assert clinician is not None
        system = session.scalar(
            select(User).where(User.clinic_id == clinician.clinic_id, User.role == "system")
        )
        assert system is not None
        system.role = "inactive_system"
        session.commit()
    unavailable = client.post(
        f"/api/v1/entries/{predecessor['id']}/regenerate",
        headers=auth(identities["clinician"]),
        json=_regeneration_payload(),
    )
    assert unavailable.status_code == 503


def test_regeneration_endpoint_maps_redaction_failure_without_provider_content(
    client, monkeypatch, identities, patient_id
) -> None:
    predecessor = _ai_entry(client, identities, patient_id)

    def fail_redaction(*_args, **_kwargs):
        raise RedactionFidelityError("Synthetic fidelity failure")

    monkeypatch.setattr(main_module, "regenerate_scribe", fail_redaction)
    response = client.post(
        f"/api/v1/entries/{predecessor['id']}/regenerate",
        headers=auth(identities["clinician"]),
        json=_regeneration_payload(),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "redaction_fidelity_failed"


def test_regeneration_domain_guards_scope_patient_type_and_state_hash(
    app, identities, patient_id, monkeypatch
) -> None:
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        other_actor = session.get(User, identities["other_clinician"])
        patient = session.get(Patient, patient_id)
        predecessor = session.scalar(
            select(Entry).where(
                Entry.patient_id == patient_id,
                Entry.entry_type == "ai_patient_session_summary",
            )
        )
        system = session.scalar(
            select(User).where(User.clinic_id == actor.clinic_id, User.role == "system")
        )
        assert actor and other_actor and patient and predecessor and system

        def invoke(*, active_actor=actor, active_patient=patient, active_entry=predecessor):
            return regenerate_scribe(
                session,
                initiating_actor=active_actor,
                system_actor=system,
                patient=active_patient,
                predecessor=active_entry,
                expected_version=active_entry.current_version,
                transcript="Synthetic source transcript with medication 20 mg confirmed.",
                source_uri="session://synthetic/domain-regeneration",
                provider=app.state.scribe_gateway,
            )

        with pytest.raises(RegenerationError, match="outside actor clinic"):
            invoke(active_actor=other_actor)

        second_patient = Patient(
            clinic_id=patient.clinic_id,
            display_name="Synthetic Second Patient",
            initials="SP",
            synthetic_record_number="SYN-0999",
            date_of_birth="1990-01-01",
            pronouns="they/them",
            synthetic=True,
        )
        session.add(second_patient)
        session.flush()
        with pytest.raises(RegenerationError, match="another patient"):
            invoke(active_patient=second_patient)

        unsupported = create_entry(
            session,
            actor=system,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="system",
            entry_type="ai_unsupported_summary",
            title="Unsupported AI proposal",
            content="AI proposal",
            visibility="internal",
            trust_state="ai_proposed",
        )
        with pytest.raises(RegenerationError, match="cannot be regenerated"):
            invoke(active_entry=unsupported)

        hashes = iter(("a" * 64, "b" * 64))
        monkeypatch.setattr(scribe_module, "_state_hash", lambda _state: next(hashes))
        with pytest.raises(RegenerationError, match="protected state"):
            invoke()
