from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.access import (
    AccessClaimError,
    issue_access_claim,
    redeem_access_claim,
    resolve_patient_session,
)
from app.models import (
    AuditEvent,
    Patient,
    PatientAccessClaim,
    PatientAccessGrant,
    PatientContact,
    User,
)
from app.seed import OTHER_PATIENT_ID, PRIMARY_CONTACT_ID

from .conftest import auth

SYNTHETIC_DEVICE_BINDING = "synthetic-browser-device-2026"


def issue_payload() -> dict:
    return {
        "contact_id": PRIMARY_CONTACT_ID,
        "purpose": "portal_access",
        "ttl_minutes": 10,
    }


def issue(client, identities, patient_id) -> dict:
    response = client.post(
        f"/api/v1/patients/{patient_id}/access-claims",
        headers=auth(identities["clinician"]),
        json=issue_payload(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def redeem_payload(token: str, *, record: str = "SYN-2048", dob: str = "1988-07-12") -> dict:
    return {
        "claim_token": token,
        "synthetic_record_number": record,
        "date_of_birth": dob,
        "device_binding": SYNTHETIC_DEVICE_BINDING,
    }


def test_phone_only_patient_claim_reaches_the_patient_projection_without_email(
    client, app, identities, patient_id
) -> None:
    claimed = issue(client, identities, patient_id)
    assert claimed["channel"] == "whatsapp"
    assert claimed["masked_destination"] == "WhatsApp ending 4567"
    assert claimed["delivery_state"] == "synthetic_rehearsal_not_sent"
    assert "email" not in claimed
    token = claimed["demo_claim_token"]

    with app.state.database.session() as session:
        stored = session.get(PatientAccessClaim, claimed["claim_id"])
        assert stored is not None
        assert stored.token_hash != token
        assert token not in str(stored.__dict__)

    redeemed = client.post(
        "/api/v1/patient-access/redeem",
        json=redeem_payload(token),
    )
    assert redeemed.status_code == 200, redeemed.text
    grant = redeemed.json()
    assert grant["email_required"] is False
    assert grant["authentication_mode"] == "channel_claim"
    with app.state.database.session() as session:
        stored_grant = session.scalar(
            select(PatientAccessGrant).where(
                PatientAccessGrant.access_claim_id == claimed["claim_id"]
            )
        )
        assert stored_grant is not None
        assert stored_grant.session_token_hash != grant["session_token"]
        assert stored_grant.device_binding_hash != SYNTHETIC_DEVICE_BINDING
        assert grant["session_token"] not in str(stored_grant.__dict__)
        assert SYNTHETIC_DEVICE_BINDING not in str(stored_grant.__dict__)
    session_headers = {
        "X-Patient-Session": grant["session_token"],
        "X-Patient-Device": SYNTHETIC_DEVICE_BINDING,
    }

    me = client.get("/api/v1/me", headers=session_headers)
    assert me.status_code == 200
    assert me.json()["role"] == "patient"
    assert me.json()["authentication_mode"] == "channel_claim"
    patients = client.get("/api/v1/patients", headers=session_headers).json()["patients"]
    assert [item["id"] for item in patients] == [patient_id]
    portal = client.get(
        f"/api/v1/patients/{patient_id}/workspace",
        headers=session_headers,
    )
    assert portal.status_code == 200
    assert portal.json()["conflicts"] == []
    assert all(item["visibility"] == "patient" for item in portal.json()["entries"])
    assert (
        client.get(
            f"/api/v1/patients/{OTHER_PATIENT_ID}/workspace",
            headers=session_headers,
        ).status_code
        == 404
    )

    replay = client.post("/api/v1/patient-access/redeem", json=redeem_payload(token))
    assert replay.status_code == 401
    assert replay.json()["detail"] == {
        "code": "access_claim_invalid",
        "message": "The access claim could not be verified",
    }
    assert (
        client.get(
            "/api/v1/me",
            headers={
                "X-Demo-User": identities["patient"],
                "X-Patient-Session": grant["session_token"],
                "X-Patient-Device": SYNTHETIC_DEVICE_BINDING,
            },
        ).status_code
        == 401
    )
    assert (
        client.get("/api/v1/me", headers={"X-Patient-Session": "invalid-session-token"}).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/me",
            headers={
                "X-Patient-Session": grant["session_token"],
                "X-Patient-Device": "different-device",
            },
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/me",
            headers={"X-Patient-Device": SYNTHETIC_DEVICE_BINDING},
        ).status_code
        == 401
    )


def test_claim_issuance_is_role_contact_scope_and_rate_limited(
    client, app, identities, patient_id
) -> None:
    for actor in (identities["patient"], identities["admin"]):
        denied = client.post(
            f"/api/v1/patients/{patient_id}/access-claims",
            headers=auth(actor),
            json=issue_payload(),
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "access_claim_issuer_required"

    missing = client.post(
        f"/api/v1/patients/{patient_id}/access-claims",
        headers=auth(identities["clinician"]),
        json={**issue_payload(), "contact_id": "missing-contact"},
    )
    assert missing.status_code == 409
    assert missing.json()["detail"]["code"] == "access_contact_not_found"

    with app.state.database.session() as session:
        contact = session.get(PatientContact, PRIMARY_CONTACT_ID)
        assert contact is not None
        contact.consent_status = "revoked"
        session.commit()
    not_ready = client.post(
        f"/api/v1/patients/{patient_id}/access-claims",
        headers=auth(identities["clinician"]),
        json=issue_payload(),
    )
    assert not_ready.status_code == 409
    assert not_ready.json()["detail"]["code"] == "access_contact_not_ready"
    with app.state.database.session() as session:
        contact = session.get(PatientContact, PRIMARY_CONTACT_ID)
        assert contact is not None
        contact.consent_status = "granted"
        session.commit()

    claims = [issue(client, identities, patient_id) for _ in range(3)]
    limited = client.post(
        f"/api/v1/patients/{patient_id}/access-claims",
        headers=auth(identities["clinician"]),
        json=issue_payload(),
    )
    assert limited.status_code == 409
    assert limited.json()["detail"]["code"] == "access_claim_rate_limited"
    with app.state.database.session() as session:
        statuses = {
            item.id: item.status
            for item in session.scalars(
                select(PatientAccessClaim).where(PatientAccessClaim.patient_id == patient_id)
            )
        }
        assert statuses[claims[-1]["claim_id"]] == "issued"
        assert {statuses[item["claim_id"]] for item in claims[:-1]} == {"revoked"}


def test_wrong_verification_locks_claim_and_never_reveals_which_field_failed(
    client, app, identities, patient_id
) -> None:
    claimed = issue(client, identities, patient_id)
    token = claimed["demo_claim_token"]
    failures = []
    for attempt in range(5):
        payload = redeem_payload(
            token,
            record="WRONG-RECORD" if attempt % 2 == 0 else "SYN-2048",
            dob="1999-01-01" if attempt % 2 else "1988-07-12",
        )
        failures.append(client.post("/api/v1/patient-access/redeem", json=payload))
    assert all(item.status_code == 401 for item in failures)
    assert len({item.text for item in failures}) == 1
    with app.state.database.session() as session:
        claim = session.get(PatientAccessClaim, claimed["claim_id"])
        assert claim is not None
        assert (claim.failed_attempts, claim.status) == (5, "locked")
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "patient_access.claim_failed",
                    AuditEvent.object_id == claim.id,
                )
            )
        )
        assert len(events) == 5
        assert all("record" not in str(event.event_metadata) for event in events)


def test_expired_claim_and_inactive_patient_identity_fail_closed(
    app, identities, patient_id
) -> None:
    baseline = datetime(2026, 9, 5, 8, 0)
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        patient = session.get(Patient, patient_id)
        assert actor is not None and patient is not None
        issued = issue_access_claim(
            session,
            actor=actor,
            patient=patient,
            contact_id=PRIMARY_CONTACT_ID,
            purpose="summary",
            ttl_minutes=5,
            now=baseline,
        )
        with pytest.raises(AccessClaimError) as expired:
            redeem_access_claim(
                session,
                claim_token=issued.claim_token,
                synthetic_record_number=patient.synthetic_record_number,
                date_of_birth=patient.date_of_birth,
                device_binding="synthetic-device-binding",
                now=baseline + timedelta(minutes=6),
            )
        assert expired.value.code == "access_claim_invalid"
        assert issued.claim.status == "expired"
        session.rollback()

    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        patient = session.get(Patient, patient_id)
        patient_actor = session.get(User, identities["patient"])
        assert actor and patient and patient_actor
        issued = issue_access_claim(
            session,
            actor=actor,
            patient=patient,
            contact_id=PRIMARY_CONTACT_ID,
            purpose="intake",
            ttl_minutes=5,
        )
        patient_actor.active = False
        session.flush()
        with pytest.raises(AccessClaimError) as inactive:
            redeem_access_claim(
                session,
                claim_token=issued.claim_token,
                synthetic_record_number=patient.synthetic_record_number,
                date_of_birth=patient.date_of_birth,
                device_binding="synthetic-device-binding",
            )
        assert inactive.value.code == "access_claim_invalid"


def test_domain_guards_and_patient_session_expiry(app, identities, patient_id) -> None:
    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        patient_actor = session.get(User, identities["patient"])
        patient = session.get(Patient, patient_id)
        other_patient = session.get(Patient, OTHER_PATIENT_ID)
        assert clinician and patient_actor and patient and other_patient
        with pytest.raises(AccessClaimError) as role_denied:
            issue_access_claim(
                session,
                actor=patient_actor,
                patient=patient,
                contact_id=PRIMARY_CONTACT_ID,
                purpose="portal_access",
                ttl_minutes=10,
            )
        assert role_denied.value.code == "access_claim_issuer_denied"
        with pytest.raises(AccessClaimError) as scope_denied:
            issue_access_claim(
                session,
                actor=clinician,
                patient=other_patient,
                contact_id=PRIMARY_CONTACT_ID,
                purpose="portal_access",
                ttl_minutes=10,
            )
        assert scope_denied.value.code == "access_claim_scope_mismatch"

        issued = issue_access_claim(
            session,
            actor=clinician,
            patient=patient,
            contact_id=PRIMARY_CONTACT_ID,
            purpose="portal_access",
            ttl_minutes=10,
        )
        redeemed = redeem_access_claim(
            session,
            claim_token=issued.claim_token,
            synthetic_record_number=patient.synthetic_record_number,
            date_of_birth=patient.date_of_birth,
            device_binding="synthetic-device-binding",
        )
        session.flush()
        with pytest.raises(AccessClaimError):
            resolve_patient_session(
                session,
                "unknown-session",
                device_binding="synthetic-device-binding",
            )
        redeemed.grant.status = "revoked"
        with pytest.raises(AccessClaimError):
            resolve_patient_session(
                session,
                redeemed.session_token,
                device_binding="synthetic-device-binding",
            )
        redeemed.grant.status = "active"
        with pytest.raises(AccessClaimError):
            resolve_patient_session(
                session,
                redeemed.session_token,
                device_binding="synthetic-device-binding",
                now=_as_aware(redeemed.grant.expires_at) + timedelta(seconds=1),
            )
        redeemed.grant.expires_at = datetime.now(UTC) + timedelta(minutes=10)
        with pytest.raises(AccessClaimError):
            resolve_patient_session(
                session,
                redeemed.session_token,
                device_binding="different-device-binding",
            )
        patient_actor.active = False
        session.flush()
        with pytest.raises(AccessClaimError):
            resolve_patient_session(
                session,
                redeemed.session_token,
                device_binding="synthetic-device-binding",
            )


def _as_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
