from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.care import edit_entry
from app.delivery import (
    DeliveryPolicyError,
    _appointment_link,
    _follow_up_owner_id,
    acknowledge_appointment_delivery,
    escalate_appointment_followups,
    queue_delivery,
    transition_delivery,
)
from app.models import (
    AuditEvent,
    CareTask,
    DeliveryFollowUp,
    Entry,
    OutboundDelivery,
    Patient,
    User,
)
from app.seed import (
    DEMO_USERS,
    OTHER_PATIENT_ID,
    PRIMARY_CONTACT_ID,
    PRIMARY_PATIENT_ID,
)

from .conftest import auth

APPOINTMENT_COPY = (
    "Your synthetic appointment is booked for 10 September 2026 at 09:30 SGT. "
    "Open https://appointments.example.test/synthetic/appointment-2048 and confirm receipt."
)


def _seeded_appointment(session) -> Entry:
    entry = session.scalar(
        select(Entry).where(
            Entry.patient_id == PRIMARY_PATIENT_ID,
            Entry.title == "Your follow-up appointment",
        )
    )
    assert entry is not None
    return entry


def _queue_api_payload(entry: dict, *, key: str) -> dict:
    return {
        "contact_id": PRIMARY_CONTACT_ID,
        "expected_version": entry["current_version"],
        "idempotency_key": key,
        "confirm_clinical_review": True,
        "confirm_patient_identity": True,
        "confirm_medication_and_dose": False,
        "communication_purpose": "appointment_invitation",
        "confirm_appointment_details": True,
        "acknowledgement_window_minutes": 60,
    }


def _service_queue(session, clinician, patient, entry, *, key: str) -> OutboundDelivery:
    return queue_delivery(
        session,
        actor=clinician,
        patient=patient,
        entry=entry,
        contact_id=PRIMARY_CONTACT_ID,
        expected_version=entry.current_version,
        idempotency_key=key,
        confirm_clinical_review=True,
        confirm_patient_identity=True,
        confirm_medication_and_dose=False,
        communication_purpose="appointment_invitation",
        confirm_appointment_details=True,
        acknowledgement_window_minutes=60,
    )


def test_appointment_delivery_distinguishes_provider_receipts_from_patient_acknowledgement(
    client, app, identities, patient_id
) -> None:
    workspace = client.get(
        f"/api/v1/patients/{patient_id}/workspace",
        headers=auth(identities["clinician"]),
    ).json()
    entry = next(
        item for item in workspace["entries"] if item["title"] == "Your follow-up appointment"
    )
    queued = client.post(
        f"/api/v1/entries/{entry['id']}/deliveries",
        headers=auth(identities["clinician"]),
        json=_queue_api_payload(entry, key="appointment-closed-loop"),
    )
    assert queued.status_code == 201
    first = queued.json()["deliveries"][0]
    assert first["communication_purpose"] == "appointment_invitation"
    assert first["follow_up"]["status"] == "pending_provider_acceptance"
    assert first["follow_up"]["acknowledge_by"] is None
    assert first["follow_up"]["acknowledged_at"] is None
    assert first["follow_up"]["escalated_at"] is None
    assert first["follow_up"]["requires_patient_acknowledgement"] is True

    too_early = client.post(
        f"/api/v1/deliveries/{first['id']}/acknowledge",
        headers=auth(identities["patient"]),
    )
    assert too_early.status_code == 409
    assert too_early.json()["detail"]["code"] == "appointment_acknowledgement_not_ready"
    assert (
        client.post(
            f"/api/v1/deliveries/{first['id']}/acknowledge",
            headers=auth(identities["clinician"]),
        ).status_code
        == 403
    )

    accepted = client.post(
        f"/api/v1/deliveries/{first['id']}/transition",
        headers=auth(identities["admin"]),
        json={"outcome": "accepted", "provider_message_id": "appointment-provider-1"},
    ).json()["deliveries"][0]
    assert accepted["follow_up"]["status"] == "pending_delivery"
    assert accepted["follow_up"]["acknowledge_by"] is None

    delivered = client.post(
        f"/api/v1/deliveries/{first['id']}/transition",
        headers=auth(identities["admin"]),
        json={"outcome": "delivered"},
    ).json()["deliveries"][0]
    assert delivered["status"] == "delivered"
    assert delivered["follow_up"]["status"] == "awaiting_patient_acknowledgement"
    assert delivered["follow_up"]["acknowledge_by"] is not None

    acknowledged = client.post(
        f"/api/v1/deliveries/{first['id']}/acknowledge",
        headers=auth(identities["patient"]),
    )
    assert acknowledged.status_code == 200
    patient_copy = acknowledged.json()["deliveries"][0]
    assert patient_copy["follow_up"]["status"] == "acknowledged"
    assert patient_copy["follow_up"]["acknowledged_at"] is not None
    assert "approval_evidence" not in patient_copy
    repeated = client.post(
        f"/api/v1/deliveries/{first['id']}/acknowledge",
        headers=auth(identities["patient"]),
    )
    assert repeated.status_code == 200
    assert repeated.json()["deliveries"][0]["follow_up"]["status"] == "acknowledged"
    assert (
        client.post(
            "/api/v1/deliveries/missing-appointment/acknowledge",
            headers=auth(identities["patient"]),
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/patients/{patient_id}/delivery-follow-ups/escalate",
            headers=auth(identities["patient"]),
            json={"as_of": "2026-09-05T12:00:00Z"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/patients/missing-patient/delivery-follow-ups/escalate",
            headers=auth(identities["clinician"]),
            json={"as_of": "2026-09-05T12:00:00Z"},
        ).status_code
        == 404
    )
    for as_of in ("2026-09-05T12:00:00", "2026-09-05T12:00:00+08:00"):
        sweep = client.post(
            f"/api/v1/patients/{patient_id}/delivery-follow-ups/escalate",
            headers=auth(identities["clinician"]),
            json={"as_of": as_of},
        )
        assert sweep.status_code == 200
        assert sweep.json()["escalated_count"] == 0

    with app.state.database.session() as session:
        delivery = session.get(OutboundDelivery, first["id"])
        follow_up = session.scalar(
            select(DeliveryFollowUp).where(DeliveryFollowUp.delivery_id == first["id"])
        )
        audit_events = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.object_id.in_([first["id"], follow_up.id]))
            )
        )
        assert delivery is not None and follow_up is not None
        assert (
            delivery.approval_evidence["appointment_link_hash"] == follow_up.appointment_link_hash
        )
        assert "appointments.example.test" not in str(
            [item.event_metadata for item in audit_events]
        )
        assert {item.action for item in audit_events} == {
            "delivery.queued",
            "delivery.transitioned",
            "delivery.patient_acknowledged",
        }


def test_overdue_invitation_escalates_once_and_late_acknowledgement_closes_task(app) -> None:
    base = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)
    with app.state.database.session() as session:
        clinician = session.get(User, DEMO_USERS["clinician"])
        staff = session.get(User, DEMO_USERS["staff"])
        admin = session.get(User, DEMO_USERS["admin"])
        patient_user = session.get(User, DEMO_USERS["patient"])
        patient = session.get(Patient, PRIMARY_PATIENT_ID)
        other_patient = session.get(Patient, OTHER_PATIENT_ID)
        entry = _seeded_appointment(session)
        assert all(
            item is not None
            for item in (clinician, staff, admin, patient_user, patient, other_patient)
        )
        assert clinician is not None and staff is not None and admin is not None
        assert patient_user is not None and patient is not None and other_patient is not None
        delivery = _service_queue(
            session, clinician, patient, entry, key="appointment-overdue-service"
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=delivery,
            outcome="accepted",
            provider_message_id="provider-overdue",
            occurred_at=base,
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=delivery,
            outcome="delivered",
            occurred_at=base,
        )
        with pytest.raises(DeliveryPolicyError, match="Only the patient"):
            acknowledge_appointment_delivery(
                session,
                actor=clinician,
                delivery=delivery,
                occurred_at=base,
            )
        patient_user.patient_id = other_patient.id
        with pytest.raises(DeliveryPolicyError, match="another patient"):
            acknowledge_appointment_delivery(
                session,
                actor=patient_user,
                delivery=delivery,
                occurred_at=base,
            )
        patient_user.patient_id = patient.id
        assert (
            escalate_appointment_followups(
                session, actor=staff, patient=patient, as_of=base + timedelta(minutes=59)
            )
            == []
        )
        with pytest.raises(DeliveryPolicyError, match="care team"):
            escalate_appointment_followups(
                session,
                actor=patient_user,
                patient=patient,
                as_of=base + timedelta(hours=2),
            )
        with pytest.raises(DeliveryPolicyError, match="another clinic"):
            escalate_appointment_followups(
                session,
                actor=staff,
                patient=other_patient,
                as_of=base + timedelta(hours=2),
            )

        escalated = escalate_appointment_followups(
            session, actor=staff, patient=patient, as_of=base + timedelta(hours=1)
        )
        assert len(escalated) == 1
        follow_up = escalated[0]
        task = session.get(CareTask, follow_up.escalation_task_id)
        assert task is not None
        assert task.status == "open" and task.urgency == "high"
        assert task.assigned_to == staff.id
        assert task.due_at is not None
        assert task.due_at.replace(tzinfo=UTC) == base + timedelta(hours=1)
        assert (
            escalate_appointment_followups(
                session,
                actor=staff,
                patient=patient,
                as_of=base + timedelta(hours=2),
            )
            == []
        )

        acknowledged = acknowledge_appointment_delivery(
            session,
            actor=patient_user,
            delivery=delivery,
            occurred_at=base + timedelta(hours=2),
        )
        assert acknowledged.status == "acknowledged_after_escalation"
        assert acknowledged.escalated_at is not None
        assert acknowledged.escalated_at.replace(tzinfo=UTC) == base + timedelta(hours=1)
        assert task.status == "completed"
        session.commit()


def test_failed_invitation_escalates_for_admin_then_retry_restores_delivery_state(app) -> None:
    base = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
    with app.state.database.session() as session:
        clinician = session.get(User, DEMO_USERS["clinician"])
        staff = session.get(User, DEMO_USERS["staff"])
        admin = session.get(User, DEMO_USERS["admin"])
        patient_user = session.get(User, DEMO_USERS["patient"])
        patient = session.get(Patient, PRIMARY_PATIENT_ID)
        entry = _seeded_appointment(session)
        assert all(item is not None for item in (clinician, staff, admin, patient_user, patient))
        assert clinician is not None and staff is not None and admin is not None
        assert patient_user is not None and patient is not None
        delivery = _service_queue(
            session, clinician, patient, entry, key="appointment-provider-failure"
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=delivery,
            outcome="failed",
            failure_code="provider_503",
            occurred_at=base,
        )
        follow_up = session.scalar(
            select(DeliveryFollowUp).where(DeliveryFollowUp.delivery_id == delivery.id)
        )
        assert follow_up is not None and follow_up.status == "delivery_failed"
        assert escalate_appointment_followups(
            session, actor=admin, patient=patient, as_of=base
        ) == [follow_up]
        task = session.get(CareTask, follow_up.escalation_task_id)
        assert task is not None and task.assigned_to == staff.id

        transition_delivery(
            session,
            actor=admin,
            delivery=delivery,
            outcome="queued",
            occurred_at=base + timedelta(minutes=1),
        )
        assert follow_up.status == "pending_provider_acceptance"
        transition_delivery(
            session,
            actor=admin,
            delivery=delivery,
            outcome="accepted",
            provider_message_id="provider-recovered",
            occurred_at=base + timedelta(minutes=2),
        )
        assert follow_up.status == "pending_delivery"
        transition_delivery(
            session,
            actor=admin,
            delivery=delivery,
            outcome="delivered",
            occurred_at=base + timedelta(minutes=3),
        )
        assert follow_up.status == "awaiting_patient_acknowledgement"
        assert follow_up.acknowledge_by == base + timedelta(minutes=63)
        acknowledged = acknowledge_appointment_delivery(
            session,
            actor=patient_user,
            delivery=delivery,
            occurred_at=base + timedelta(minutes=64),
        )
        assert acknowledged.status == "acknowledged_after_escalation"
        assert task.status == "completed"


def test_admin_follow_up_assignment_falls_back_to_clinician_and_fails_without_owner(app) -> None:
    with app.state.database.session() as session:
        staff = session.get(User, DEMO_USERS["staff"])
        clinician = session.get(User, DEMO_USERS["clinician"])
        admin = session.get(User, DEMO_USERS["admin"])
        assert staff is not None and clinician is not None and admin is not None
        assert _follow_up_owner_id(session, staff) == staff.id
        assert _follow_up_owner_id(session, admin) == staff.id
        staff.role = "unavailable"
        session.flush()
        assert _follow_up_owner_id(session, admin) == clinician.id
        clinician.role = "unavailable"
        session.flush()
        with pytest.raises(DeliveryPolicyError, match="staff or clinician owner"):
            _follow_up_owner_id(session, admin)
        session.rollback()


def test_delivered_appointment_correction_supersedes_the_original_follow_up(app) -> None:
    base = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    with app.state.database.session() as session:
        clinician = session.get(User, DEMO_USERS["clinician"])
        admin = session.get(User, DEMO_USERS["admin"])
        patient = session.get(Patient, PRIMARY_PATIENT_ID)
        entry = _seeded_appointment(session)
        assert clinician is not None and admin is not None and patient is not None
        original = _service_queue(
            session, clinician, patient, entry, key="appointment-correction-original"
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=original,
            outcome="accepted",
            provider_message_id="provider-original",
            occurred_at=base,
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=original,
            outcome="delivered",
            occurred_at=base,
        )
        original_follow_up = session.scalar(
            select(DeliveryFollowUp).where(DeliveryFollowUp.delivery_id == original.id)
        )
        assert original_follow_up is not None
        assert escalate_appointment_followups(
            session,
            actor=clinician,
            patient=patient,
            as_of=base + timedelta(minutes=60),
        ) == [original_follow_up]
        original_task = session.get(CareTask, original_follow_up.escalation_task_id)
        assert original_task is not None and original_task.status == "open"

        edit_entry(
            session,
            actor=clinician,
            entry=entry,
            content=APPOINTMENT_COPY.replace("appointment-2048", "appointment-2048-corrected"),
            expected_version=entry.current_version,
            reason="Correct the appointment invitation",
        )
        correction = queue_delivery(
            session,
            actor=clinician,
            patient=patient,
            entry=entry,
            contact_id=PRIMARY_CONTACT_ID,
            expected_version=entry.current_version,
            idempotency_key="appointment-correction-replacement",
            confirm_clinical_review=True,
            confirm_patient_identity=True,
            confirm_medication_and_dose=False,
            communication_purpose="appointment_invitation",
            confirm_appointment_details=True,
            acknowledgement_window_minutes=60,
            correction_for=original,
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=correction,
            outcome="accepted",
            provider_message_id="provider-correction",
            occurred_at=base + timedelta(minutes=61),
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=correction,
            outcome="delivered",
            occurred_at=base + timedelta(minutes=62),
        )
        correction_follow_up = session.scalar(
            select(DeliveryFollowUp).where(DeliveryFollowUp.delivery_id == correction.id)
        )
        assert original_follow_up.status == "superseded"
        assert original_follow_up.updated_at == base + timedelta(minutes=62)
        assert original_task.status == "completed"
        assert correction_follow_up is not None
        assert correction_follow_up.status == "awaiting_patient_acknowledgement"

        un_escalated_original = _service_queue(
            session,
            clinician,
            patient,
            entry,
            key="appointment-correction-without-escalation",
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=un_escalated_original,
            outcome="accepted",
            provider_message_id="provider-un-escalated-original",
            occurred_at=base + timedelta(minutes=70),
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=un_escalated_original,
            outcome="delivered",
            occurred_at=base + timedelta(minutes=70),
        )
        edit_entry(
            session,
            actor=clinician,
            entry=entry,
            content=APPOINTMENT_COPY.replace("appointment-2048", "appointment-2048-final"),
            expected_version=entry.current_version,
            reason="Exercise an un-escalated appointment correction",
        )
        un_escalated_correction = queue_delivery(
            session,
            actor=clinician,
            patient=patient,
            entry=entry,
            contact_id=PRIMARY_CONTACT_ID,
            expected_version=entry.current_version,
            idempotency_key="appointment-correction-without-escalation-replacement",
            confirm_clinical_review=True,
            confirm_patient_identity=True,
            confirm_medication_and_dose=False,
            communication_purpose="appointment_invitation",
            confirm_appointment_details=True,
            acknowledgement_window_minutes=60,
            correction_for=un_escalated_original,
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=un_escalated_correction,
            outcome="accepted",
            provider_message_id="provider-un-escalated-correction",
            occurred_at=base + timedelta(minutes=71),
        )
        transition_delivery(
            session,
            actor=admin,
            delivery=un_escalated_correction,
            outcome="delivered",
            occurred_at=base + timedelta(minutes=72),
        )
        un_escalated_follow_up = session.scalar(
            select(DeliveryFollowUp).where(DeliveryFollowUp.delivery_id == un_escalated_original.id)
        )
        assert un_escalated_follow_up is not None
        assert un_escalated_follow_up.status == "superseded"
        assert un_escalated_follow_up.escalation_task_id is None


def test_appointment_validation_idempotency_and_correction_purpose_are_fail_closed(app) -> None:
    valid = "Open https://appointments.example.test/synthetic/a."
    assert _appointment_link(valid) == "https://appointments.example.test/synthetic/a"
    for content in (
        "No link here.",
        "https://appointments.example.test/synthetic/a https://appointments.example.test/synthetic/b",
        "https://evil.example/synthetic/a",
        "http://appointments.example.test/synthetic/a",
        "https://appointments.example.test:444/synthetic/a",
        "https://appointments.example.test/synthetic/a?token=secret",
        'https://appointments.example.test/synthetic/a"',
        "https://appointments.example.test:invalid/synthetic/a",
        "https://user:secret@appointments.example.test/synthetic/a",
        "https://appointments.example.test/wrong/a",
        "https://appointments.example.test/synthetic/a#fragment",
    ):
        with pytest.raises(DeliveryPolicyError):
            _appointment_link(content)

    with app.state.database.session() as session:
        clinician = session.get(User, DEMO_USERS["clinician"])
        admin = session.get(User, DEMO_USERS["admin"])
        patient = session.get(Patient, PRIMARY_PATIENT_ID)
        entry = _seeded_appointment(session)
        assert clinician is not None and admin is not None and patient is not None
        base = dict(
            session=session,
            actor=clinician,
            patient=patient,
            entry=entry,
            contact_id=PRIMARY_CONTACT_ID,
            expected_version=entry.current_version,
            idempotency_key="appointment-validation",
            confirm_clinical_review=True,
            confirm_patient_identity=True,
            confirm_medication_and_dose=False,
        )
        with pytest.raises(DeliveryPolicyError, match="not supported"):
            queue_delivery(**base, communication_purpose="unknown")
        with pytest.raises(DeliveryPolicyError, match="between five minutes"):
            queue_delivery(**base, acknowledgement_window_minutes=4)
        with pytest.raises(DeliveryPolicyError, match="explicit confirmation"):
            queue_delivery(**base, communication_purpose="appointment_invitation")

        ordinary = queue_delivery(**base, communication_purpose="patient_instruction")
        assert ordinary.approval_evidence["appointment_link_hash"] is None
        with pytest.raises(DeliveryPolicyError, match="another payload"):
            queue_delivery(
                **base,
                communication_purpose="appointment_invitation",
                confirm_appointment_details=True,
            )

        transition_delivery(
            session,
            actor=admin,
            delivery=ordinary,
            outcome="accepted",
            provider_message_id="provider-ordinary",
        )
        with pytest.raises(DeliveryPolicyError, match="not an appointment"):
            acknowledge_appointment_delivery(
                session,
                actor=session.get(User, DEMO_USERS["patient"]),
                delivery=ordinary,
            )
        transition_delivery(session, actor=admin, delivery=ordinary, outcome="delivered")
        edited = edit_entry(
            session,
            actor=clinician,
            entry=entry,
            content=APPOINTMENT_COPY,
            expected_version=entry.current_version,
            reason="Test purpose-preserving appointment correction",
        )
        assert edited.version == entry.current_version
        with pytest.raises(DeliveryPolicyError, match="retain the original"):
            queue_delivery(
                **{
                    **base,
                    "expected_version": entry.current_version,
                    "idempotency_key": "purpose-mismatch-correction",
                    "correction_for": ordinary,
                },
                communication_purpose="appointment_invitation",
                confirm_appointment_details=True,
            )
