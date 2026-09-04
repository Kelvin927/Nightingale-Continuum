from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.care import create_entry, edit_entry
from app.database import Database
from app.delivery import DeliveryPolicyError, queue_delivery, transition_delivery
from app.models import Entry, OutboundDelivery, Patient, PatientContact, User
from app.seed import (
    DEMO_USERS,
    OTHER_PATIENT_ID,
    PRIMARY_CONTACT_ID,
    PRIMARY_PATIENT_ID,
    _ensure_demo_contact,
)

from .conftest import auth, workspace


def _patient_summary(session) -> Entry:
    entry = session.scalar(
        select(Entry).where(
            Entry.patient_id == PRIMARY_PATIENT_ID,
            Entry.entry_type == "patient_summary",
        )
    )
    assert entry is not None
    return entry


def _queue_payload(entry: dict, *, key: str, dose: bool = False) -> dict:
    return {
        "contact_id": PRIMARY_CONTACT_ID,
        "expected_version": entry["current_version"],
        "idempotency_key": key,
        "confirm_clinical_review": True,
        "confirm_patient_identity": True,
        "confirm_medication_and_dose": dose,
    }


def test_phone_only_patient_has_no_email_dependency_and_receipts_distinguish_acceptance(
    client, identities, patient_id
) -> None:
    readiness = client.get(
        f"/api/v1/patients/{patient_id}/delivery-readiness",
        headers=auth(identities["patient"]),
    )
    assert readiness.status_code == 200
    contacts = readiness.json()["contacts"]
    assert [(item["channel"], item["preferred"]) for item in contacts] == [("whatsapp", True)]
    assert "email" not in str(contacts).lower()

    clinician_workspace = workspace(client, identities["clinician"], patient_id)
    entry = next(
        item for item in clinician_workspace["entries"] if item["entry_type"] == "patient_summary"
    )
    payload = _queue_payload(entry, key="visit-summary-001")
    denied = client.post(
        f"/api/v1/entries/{entry['id']}/deliveries",
        headers=auth(identities["staff"]),
        json=payload,
    )
    assert denied.status_code == 403

    incomplete = client.post(
        f"/api/v1/entries/{entry['id']}/deliveries",
        headers=auth(identities["clinician"]),
        json={**payload, "confirm_patient_identity": False},
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["detail"]["code"] == "delivery_attestation_incomplete"

    queued = client.post(
        f"/api/v1/entries/{entry['id']}/deliveries",
        headers=auth(identities["clinician"]),
        json=payload,
    )
    assert queued.status_code == 201
    delivery = queued.json()["deliveries"][0]
    assert delivery["status"] == "queued"
    assert "not accepted" in delivery["receipt_meaning"]

    invalid_transition = client.post(
        f"/api/v1/deliveries/{delivery['id']}/transition",
        headers=auth(identities["admin"]),
        json={"outcome": "delivered"},
    )
    assert invalid_transition.status_code == 409
    assert invalid_transition.json()["detail"]["code"] == "delivery_transition_invalid"
    assert (
        client.post(
            "/api/v1/deliveries/missing-delivery/transition",
            headers=auth(identities["admin"]),
            json={"outcome": "failed", "failure_code": "provider_503"},
        ).status_code
        == 404
    )

    repeated = client.post(
        f"/api/v1/entries/{entry['id']}/deliveries",
        headers=auth(identities["clinician"]),
        json=payload,
    )
    assert repeated.status_code == 201
    assert [item["id"] for item in repeated.json()["deliveries"]] == [delivery["id"]]

    accepted = client.post(
        f"/api/v1/deliveries/{delivery['id']}/transition",
        headers=auth(identities["admin"]),
        json={"outcome": "accepted", "provider_message_id": "wa-provider-001"},
    )
    assert accepted.status_code == 200
    accepted_copy = accepted.json()["deliveries"][0]
    assert accepted_copy["status"] == "accepted"
    assert "not yet confirmed" in accepted_copy["receipt_meaning"]

    delivered = client.post(
        f"/api/v1/deliveries/{delivery['id']}/transition",
        headers=auth(identities["admin"]),
        json={"outcome": "delivered"},
    )
    assert delivered.status_code == 200
    assert delivered.json()["deliveries"][0]["status"] == "delivered"
    patient_receipt = client.get(
        f"/api/v1/patients/{patient_id}/delivery-readiness",
        headers=auth(identities["patient"]),
    ).json()["deliveries"][0]
    assert "approved_by" not in patient_receipt
    assert "approval_evidence" not in patient_receipt
    assert "failure_code" not in patient_receipt


def test_wrong_dose_correction_preserves_original_and_current_versions_side_by_side(
    client, app, identities, patient_id
) -> None:
    clinician_workspace = workspace(client, identities["clinician"], patient_id)
    original_entry = next(
        item for item in clinician_workspace["entries"] if item["entry_type"] == "patient_summary"
    )
    queued = client.post(
        f"/api/v1/entries/{original_entry['id']}/deliveries",
        headers=auth(identities["clinician"]),
        json=_queue_payload(original_entry, key="dose-copy-original"),
    ).json()["deliveries"][0]
    for outcome, extra in (
        ("accepted", {"provider_message_id": "provider-dose-original"}),
        ("delivered", {}),
    ):
        response = client.post(
            f"/api/v1/deliveries/{queued['id']}/transition",
            headers=auth(identities["admin"]),
            json={"outcome": outcome, **extra},
        )
        assert response.status_code == 200

    corrected_text = (
        "Correction: take lisinopril 10 mg daily, not 20 mg. Contact the care team with questions."
    )
    edited = client.patch(
        f"/api/v1/entries/{original_entry['id']}",
        headers=auth(identities["clinician"]),
        json={
            "content": corrected_text,
            "expected_version": original_entry["current_version"],
            "reason": "Correct the patient-facing dose after delivery",
        },
    )
    assert edited.status_code == 200
    assert edited.json()["current_version"] == original_entry["current_version"] + 1

    correction_payload = {
        **_queue_payload(edited.json(), key="dose-copy-correction", dose=False),
        "replacement_entry_id": original_entry["id"],
    }
    assert (
        client.post(
            f"/api/v1/deliveries/{queued['id']}/corrections",
            headers=auth(identities["staff"]),
            json=correction_payload,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/deliveries/missing-delivery/corrections",
            headers=auth(identities["clinician"]),
            json=correction_payload,
        ).status_code
        == 404
    )
    blocked = client.post(
        f"/api/v1/deliveries/{queued['id']}/corrections",
        headers=auth(identities["clinician"]),
        json=correction_payload,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "medication_dose_attestation_required"

    correction = client.post(
        f"/api/v1/deliveries/{queued['id']}/corrections",
        headers=auth(identities["clinician"]),
        json={**correction_payload, "confirm_medication_and_dose": True},
    )
    assert correction.status_code == 201
    correction_copy = correction.json()["deliveries"][0]
    assert correction_copy["correction_for_id"] == queued["id"]
    assert correction_copy["content_snapshot"] == corrected_text

    for outcome, extra in (
        ("accepted", {"provider_message_id": "provider-dose-correction"}),
        ("delivered", {}),
    ):
        response = client.post(
            f"/api/v1/deliveries/{correction_copy['id']}/transition",
            headers=auth(identities["admin"]),
            json={"outcome": outcome, **extra},
        )
        assert response.status_code == 200

    final = client.get(
        f"/api/v1/patients/{patient_id}/delivery-readiness",
        headers=auth(identities["clinician"]),
    ).json()
    by_id = {item["id"]: item for item in final["deliveries"]}
    assert by_id[queued["id"]]["status"] == "superseded"
    assert by_id[queued["id"]]["source_is_current"] is False
    assert by_id[queued["id"]]["content_snapshot"] != corrected_text
    assert by_id[correction_copy["id"]]["status"] == "delivered"
    assert by_id[correction_copy["id"]]["source_is_current"] is True
    assert "preserve the original side by side" in final["safety_contract"]

    with app.state.database.session() as session:
        original = session.get(OutboundDelivery, queued["id"])
        replacement = session.get(OutboundDelivery, correction_copy["id"])
        assert original is not None and replacement is not None
        assert original.content_hash != replacement.content_hash
        assert original.superseded_at == replacement.delivered_at


def test_delivery_service_rejects_scope_release_contact_and_idempotency_failures(app) -> None:
    with app.state.database.session() as session:
        clinician = session.get(User, DEMO_USERS["clinician"])
        staff = session.get(User, DEMO_USERS["staff"])
        patient = session.get(Patient, PRIMARY_PATIENT_ID)
        other_patient = session.get(Patient, OTHER_PATIENT_ID)
        entry = _patient_summary(session)
        contact = session.get(PatientContact, PRIMARY_CONTACT_ID)
        assert all(item is not None for item in (clinician, staff, patient, other_patient, contact))
        assert clinician is not None and staff is not None and patient is not None
        assert other_patient is not None and contact is not None

        base = dict(
            session=session,
            actor=clinician,
            patient=patient,
            entry=entry,
            contact_id=contact.id,
            expected_version=entry.current_version,
            idempotency_key="service-base",
            confirm_clinical_review=True,
            confirm_patient_identity=True,
            confirm_medication_and_dose=True,
        )
        with pytest.raises(DeliveryPolicyError, match="clinician"):
            queue_delivery(**{**base, "actor": staff})
        with pytest.raises(DeliveryPolicyError, match="one clinic"):
            queue_delivery(**{**base, "patient": other_patient})

        second_patient = Patient(
            id="patient-second-northstar",
            clinic_id=patient.clinic_id,
            display_name="Synthetic Second Patient",
            initials="SP",
            synthetic_record_number="SYN-SECOND",
            date_of_birth="2000-01-01",
            pronouns="they/them",
            synthetic=True,
        )
        session.add(second_patient)
        session.flush()
        with pytest.raises(DeliveryPolicyError, match="does not belong"):
            queue_delivery(**{**base, "patient": second_patient})

        internal = create_entry(
            session,
            actor=clinician,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Internal only",
            content="Internal clinical content.",
            visibility="internal",
            trust_state="clinician_confirmed",
        )
        with pytest.raises(DeliveryPolicyError, match="patient-facing"):
            queue_delivery(**{**base, "entry": internal})
        with pytest.raises(DeliveryPolicyError, match="changed"):
            queue_delivery(**{**base, "expected_version": entry.current_version + 1})
        with pytest.raises(DeliveryPolicyError, match="identity"):
            queue_delivery(**{**base, "confirm_clinical_review": False})
        with pytest.raises(DeliveryPolicyError, match="identity"):
            queue_delivery(**{**base, "confirm_patient_identity": False})
        with pytest.raises(DeliveryPolicyError, match="contact route"):
            queue_delivery(**{**base, "contact_id": "missing-contact"})

        contact.active = False
        with pytest.raises(DeliveryPolicyError, match="inactive"):
            queue_delivery(**base)
        contact.active = True
        contact.verified_at = None
        with pytest.raises(DeliveryPolicyError, match="unverified"):
            queue_delivery(**base)
        contact.verified_at = datetime(2026, 1, 1, tzinfo=UTC)
        contact.consent_status = "revoked"
        with pytest.raises(DeliveryPolicyError, match="unconsented"):
            queue_delivery(**base)
        contact.consent_status = "granted"

        delivery = queue_delivery(**base)
        assert queue_delivery(**base).id == delivery.id
        edit_entry(
            session,
            actor=clinician,
            entry=entry,
            content="Updated safe patient summary.",
            expected_version=entry.current_version,
            reason="Exercise idempotency collision",
        )
        with pytest.raises(DeliveryPolicyError, match="another payload"):
            queue_delivery(
                **{
                    **base,
                    "expected_version": entry.current_version,
                    "idempotency_key": "service-base",
                }
            )

        correction_base = {
            **base,
            "expected_version": entry.current_version,
            "idempotency_key": "correction-scope",
            "correction_for": delivery,
        }
        delivery.clinic_id = "clinic-wrong"
        with pytest.raises(DeliveryPolicyError, match="another scope"):
            queue_delivery(**correction_base)
        delivery.clinic_id = patient.clinic_id
        with pytest.raises(DeliveryPolicyError, match="accepted or delivered"):
            queue_delivery(**correction_base)
        delivery.status = "delivered"
        correction = queue_delivery(**correction_base)
        assert correction.correction_for_id == delivery.id
        with pytest.raises(DeliveryPolicyError, match="already exists"):
            queue_delivery(
                **{
                    **correction_base,
                    "idempotency_key": "second-active-correction",
                }
            )


def test_delivery_transition_failure_retry_and_policy_guards(app) -> None:
    with app.state.database.session() as session:
        clinician = session.get(User, DEMO_USERS["clinician"])
        admin = session.get(User, DEMO_USERS["admin"])
        other = session.get(User, DEMO_USERS["other_clinician"])
        patient = session.get(Patient, PRIMARY_PATIENT_ID)
        entry = _patient_summary(session)
        assert (
            clinician is not None
            and admin is not None
            and other is not None
            and patient is not None
        )
        delivery = queue_delivery(
            session,
            actor=clinician,
            patient=patient,
            entry=entry,
            contact_id=PRIMARY_CONTACT_ID,
            expected_version=entry.current_version,
            idempotency_key="transition-guards",
            confirm_clinical_review=True,
            confirm_patient_identity=True,
            confirm_medication_and_dose=True,
        )
        with pytest.raises(DeliveryPolicyError, match="control plane"):
            transition_delivery(session, actor=clinician, delivery=delivery, outcome="accepted")
        other.role = "admin"
        with pytest.raises(DeliveryPolicyError, match="another clinic"):
            transition_delivery(session, actor=other, delivery=delivery, outcome="accepted")
        with pytest.raises(DeliveryPolicyError, match="not allowed"):
            transition_delivery(session, actor=admin, delivery=delivery, outcome="delivered")
        with pytest.raises(DeliveryPolicyError, match="message identifier"):
            transition_delivery(session, actor=admin, delivery=delivery, outcome="accepted")
        with pytest.raises(DeliveryPolicyError, match="failure code"):
            transition_delivery(session, actor=admin, delivery=delivery, outcome="failed")
        with pytest.raises(DeliveryPolicyError, match="failure code"):
            transition_delivery(
                session,
                actor=admin,
                delivery=delivery,
                outcome="failed",
                failure_code="UNSAFE FAILURE",
            )

        failed = transition_delivery(
            session,
            actor=admin,
            delivery=delivery,
            outcome="failed",
            failure_code="provider_503",
        )
        assert failed.status == "failed" and failed.attempt_count == 1
        assert (
            transition_delivery(session, actor=admin, delivery=delivery, outcome="failed").status
            == "failed"
        )
        retried = transition_delivery(session, actor=admin, delivery=delivery, outcome="queued")
        assert retried.status == "queued" and retried.failure_code is None
        accepted = transition_delivery(
            session,
            actor=admin,
            delivery=delivery,
            outcome="accepted",
            provider_message_id="patient@example.test external identifier",
        )
        assert accepted.provider_message_id is not None
        assert accepted.provider_message_id.startswith("sha256:")
        delivered = transition_delivery(
            session,
            actor=admin,
            delivery=delivery,
            outcome="delivered",
            occurred_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        assert delivered.delivered_at == datetime(2026, 2, 1, tzinfo=UTC)

        delivery.status = "accepted"
        delivery.correction_for_id = "missing-original-delivery"
        with pytest.raises(DeliveryPolicyError, match="cannot be resolved"):
            transition_delivery(session, actor=admin, delivery=delivery, outcome="delivered")


def test_demo_contact_backfill_is_safe_on_an_empty_database() -> None:
    database = Database("sqlite://")
    database.create_all()
    with database.session() as session:
        _ensure_demo_contact(session)
        assert session.scalar(select(PatientContact)) is None
    database.engine.dispose()
