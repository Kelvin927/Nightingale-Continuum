from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.conflicts import (
    ConflictResolutionError,
    _source_evidence,
    resolve_conflict,
    serialize_conflict,
)
from app.models import AuditEvent, Conflict, Entry, EntryVersion, User

from .conftest import auth


def allergy_conflict(session) -> Conflict:
    conflict = session.scalar(
        select(Conflict).where(Conflict.conflict_type == "allergy_status_mismatch")
    )
    assert conflict is not None
    return conflict


def test_workspace_exposes_both_immutable_sources_without_selecting_a_winner(
    client, identities, patient_id
) -> None:
    response = client.get(
        f"/api/v1/patients/{patient_id}/workspace",
        headers=auth(identities["clinician"]),
    )
    assert response.status_code == 200
    conflict = next(
        item
        for item in response.json()["conflicts"]
        if item["conflict_type"] == "allergy_status_mismatch"
    )
    assert conflict["status"] == "open"
    assert conflict["resolution"] == {
        "decision": None,
        "rationale": None,
        "resolved_by": None,
    }
    assert conflict["decision_policy"].startswith("No automatic winner")
    assert {conflict["left"]["owner_role"], conflict["right"]["owner_role"]} == {
        "patient",
        "clinician",
    }
    assert "no known drug allergies" in conflict["left"]["content"]
    assert "penicillin caused facial swelling" in conflict["right"]["content"]
    for side in (conflict["left"], conflict["right"]):
        assert side["state"] == "available"
        assert side["source_is_current"] is True
        assert len(side["content_hash"]) == 64
        assert side["author"]["role"] in {"patient", "clinician"}

    patient_view = client.get(
        f"/api/v1/patients/{patient_id}/workspace",
        headers=auth(identities["patient"]),
    )
    assert patient_view.status_code == 200
    assert patient_view.json()["conflicts"] == []


def test_conflict_resolution_requires_clinician_and_source_attestation(
    client, app, identities, patient_id
) -> None:
    with app.state.database.session() as session:
        conflict_id = allergy_conflict(session).id

    no_attestation = client.post(
        f"/api/v1/conflicts/{conflict_id}/resolve",
        headers=auth(identities["clinician"]),
        json={
            "decision": "confirm_left",
            "rationale": "Patient statement was reviewed directly.",
            "confirm_sources_reviewed": False,
        },
    )
    assert no_attestation.status_code == 409
    assert no_attestation.json()["detail"]["code"] == "source_review_attestation_required"

    staff_denied = client.post(
        f"/api/v1/conflicts/{conflict_id}/resolve",
        headers=auth(identities["staff"]),
        json={
            "decision": "confirm_left",
            "rationale": "Staff cannot determine clinical truth.",
            "confirm_sources_reviewed": True,
        },
    )
    assert staff_denied.status_code == 409
    assert staff_denied.json()["detail"]["code"] == "clinician_conflict_review_required"

    resolved = client.post(
        f"/api/v1/conflicts/{conflict_id}/resolve",
        headers=auth(identities["clinician"]),
        json={
            "decision": "confirm_right",
            "rationale": "Reaction history was confirmed against both source versions.",
            "confirm_sources_reviewed": True,
        },
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["status"] == "resolved"
    assert body["resolution"] == {
        "decision": "confirm_right",
        "rationale": "Reaction history was confirmed against both source versions.",
        "resolved_by": identities["clinician"],
    }

    repeated = client.post(
        f"/api/v1/conflicts/{conflict_id}/resolve",
        headers=auth(identities["clinician"]),
        json={
            "decision": "confirm_left",
            "rationale": "A second decision must not overwrite the first.",
            "confirm_sources_reviewed": True,
        },
    )
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "conflict_not_open"

    with app.state.database.session() as session:
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "conflict.reviewed",
                AuditEvent.object_id == conflict_id,
            )
        )
        assert event is not None
        assert event.event_metadata == {
            "conflict_decision": "confirm_right",
            "sources_reviewed": True,
        }

    refreshed = client.get(
        f"/api/v1/patients/{patient_id}/workspace",
        headers=auth(identities["clinician"]),
    )
    same = next(item for item in refreshed.json()["conflicts"] if item["id"] == conflict_id)
    assert same["status"] == "resolved"


def test_unresolved_escalation_is_explicit_and_cross_tenant_ids_are_concealed(
    client, app, identities
) -> None:
    with app.state.database.session() as session:
        conflict = session.scalar(
            select(Conflict).where(Conflict.conflict_type == "medication_plan_uncertainty")
        )
        assert conflict is not None
        conflict_id = conflict.id

    escalated = client.post(
        f"/api/v1/conflicts/{conflict_id}/resolve",
        headers=auth(identities["clinician"]),
        json={
            "decision": "escalate_unresolved",
            "rationale": "Current evidence cannot determine the intended dose safely.",
            "confirm_sources_reviewed": True,
        },
    )
    assert escalated.status_code == 200
    assert escalated.json()["status"] == "escalated"
    assert escalated.json()["resolution"]["decision"] == "escalate_unresolved"

    concealed = client.post(
        f"/api/v1/conflicts/{conflict_id}/resolve",
        headers=auth(identities["other_clinician"]),
        json={
            "decision": "confirm_left",
            "rationale": "Cross-clinic access must be concealed.",
            "confirm_sources_reviewed": True,
        },
    )
    missing = client.post(
        "/api/v1/conflicts/missing-conflict/resolve",
        headers=auth(identities["clinician"]),
        json={
            "decision": "confirm_left",
            "rationale": "Missing conflict must be concealed.",
            "confirm_sources_reviewed": True,
        },
    )
    assert concealed.status_code == missing.status_code == 404


def test_direct_conflict_guards_and_legacy_resolution_serialization(app, identities) -> None:
    with app.state.database.session() as session:
        conflict = allergy_conflict(session)
        clinician = session.get(User, identities["clinician"])
        other = session.get(User, identities["other_clinician"])
        assert clinician is not None and other is not None

        with pytest.raises(ConflictResolutionError, match="outside clinic"):
            resolve_conflict(
                session,
                actor=other,
                conflict=conflict,
                decision="confirm_left",
                rationale="Cross clinic",
                confirm_sources_reviewed=True,
            )
        with pytest.raises(ConflictResolutionError, match="Unknown"):
            resolve_conflict(
                session,
                actor=clinician,
                conflict=conflict,
                decision="invented",
                rationale="Invalid direct call",
                confirm_sources_reviewed=True,
            )

        conflict.disposition = "Legacy free-text disposition"
        conflict.resolved_by = clinician.id
        serialized = serialize_conflict(session, conflict)
        assert serialized["resolution"] == {
            "decision": None,
            "rationale": "Legacy free-text disposition",
            "resolved_by": clinician.id,
        }


def test_source_serializer_fails_closed_for_missing_or_cross_scope_evidence() -> None:
    conflict = SimpleNamespace(clinic_id="clinic-a")
    missing_session = SimpleNamespace(get=lambda *_args: None)
    assert _source_evidence(missing_session, conflict, "version-x") == {
        "state": "unavailable",
        "version_id": "version-x",
    }

    version = SimpleNamespace(entry_id="entry-x")

    def no_entry(model, _identifier):
        return version if model is EntryVersion else None

    assert _source_evidence(SimpleNamespace(get=no_entry), conflict, "version-x")["state"] == (
        "unavailable"
    )

    cross_entry = SimpleNamespace(clinic_id="clinic-b")

    def cross_scope(model, _identifier):
        return version if model is EntryVersion else cross_entry

    assert (
        _source_evidence(SimpleNamespace(get=cross_scope), conflict, "version-x")["state"]
        == "unavailable"
    )

    available_entry = SimpleNamespace(
        id="entry-x",
        clinic_id="clinic-a",
        title="Synthetic source",
        entry_type="patient_insight",
        owner_role="patient",
        trust_state="human_authored",
        author_id=None,
        current_version_id="version-x",
    )
    available_version = SimpleNamespace(
        id="version-x",
        entry_id="entry-x",
        version=1,
        content="Synthetic evidence",
        content_hash="a" * 64,
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )

    def available(model, _identifier):
        if model is EntryVersion:
            return available_version
        if model is Entry:
            return available_entry
        raise AssertionError("No author lookup is expected")

    evidence = _source_evidence(SimpleNamespace(get=available), conflict, "version-x")
    assert evidence["state"] == "available"
    assert evidence["author"] is None
    assert evidence["source_is_current"] is True


def test_conflict_request_rejects_unknown_fields_and_false_boolean_strings(
    client, app, identities
) -> None:
    with app.state.database.session() as session:
        conflict_id = allergy_conflict(session).id
    invalid = client.post(
        f"/api/v1/conflicts/{conflict_id}/resolve",
        headers=auth(identities["clinician"]),
        json={
            "decision": "confirm_left",
            "rationale": "Enough characters for validation.",
            "confirm_sources_reviewed": "yes",
            "unexpected": True,
        },
    )
    assert invalid.status_code == 422
    locations = {tuple(item["loc"]) for item in invalid.json()["detail"]}
    assert ("body", "confirm_sources_reviewed") in locations
    assert ("body", "unexpected") in locations
