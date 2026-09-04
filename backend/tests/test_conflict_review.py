from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.conflicts import (
    ConflictResolutionError,
    _allergy_assertions,
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
        assert event.actor_id == identities["clinician"]
        assert event.object_type == "conflict"
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

        with pytest.raises(ConflictResolutionError) as cross_scope:
            resolve_conflict(
                session,
                actor=other,
                conflict=conflict,
                decision="confirm_left",
                rationale="Cross clinic",
                confirm_sources_reviewed=True,
            )
        assert (cross_scope.value.code, str(cross_scope.value)) == (
            "conflict_scope_mismatch",
            "Conflict is outside clinic",
        )

        staff = session.get(User, identities["staff"])
        assert staff is not None
        with pytest.raises(ConflictResolutionError) as wrong_role:
            resolve_conflict(
                session,
                actor=staff,
                conflict=conflict,
                decision="confirm_left",
                rationale="Wrong role",
                confirm_sources_reviewed=True,
            )
        assert (wrong_role.value.code, str(wrong_role.value)) == (
            "clinician_conflict_review_required",
            "Only a clinician can resolve a clinical contradiction",
        )

        with pytest.raises(ConflictResolutionError) as invalid_decision:
            resolve_conflict(
                session,
                actor=clinician,
                conflict=conflict,
                decision="invented",
                rationale="Invalid direct call",
                confirm_sources_reviewed=True,
            )
        assert (invalid_decision.value.code, str(invalid_decision.value)) == (
            "invalid_conflict_decision",
            "Unknown conflict decision",
        )

        with pytest.raises(ConflictResolutionError) as no_attestation:
            resolve_conflict(
                session,
                actor=clinician,
                conflict=conflict,
                decision="confirm_left",
                rationale="Missing attestation",
                confirm_sources_reviewed=False,
            )
        assert (no_attestation.value.code, str(no_attestation.value)) == (
            "source_review_attestation_required",
            "Both immutable source versions must be reviewed",
        )

        conflict.status = "resolved"
        with pytest.raises(ConflictResolutionError) as already_closed:
            resolve_conflict(
                session,
                actor=clinician,
                conflict=conflict,
                decision="confirm_left",
                rationale="Already closed",
                confirm_sources_reviewed=True,
            )
        assert (already_closed.value.code, str(already_closed.value)) == (
            "conflict_not_open",
            "Only an open conflict can receive a decision",
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

    assert _source_evidence(SimpleNamespace(get=no_entry), conflict, "version-x") == {
        "state": "unavailable",
        "version_id": "version-x",
    }

    cross_entry = SimpleNamespace(clinic_id="clinic-b")

    def cross_scope(model, _identifier):
        return version if model is EntryVersion else cross_entry

    assert _source_evidence(SimpleNamespace(get=cross_scope), conflict, "version-x") == {
        "state": "unavailable",
        "version_id": "version-x",
    }

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
    assert evidence == {
        "state": "available",
        "entry_id": "entry-x",
        "entry_title": "Synthetic source",
        "entry_type": "patient_insight",
        "owner_role": "patient",
        "trust_state": "human_authored",
        "author": None,
        "version_id": "version-x",
        "version": 1,
        "content": "Synthetic evidence",
        "content_hash": "a" * 64,
        "source_is_current": True,
        "created_at": "2026-09-05T00:00:00+00:00",
    }


def test_source_serializer_preserves_the_exact_author_contract() -> None:
    conflict = SimpleNamespace(clinic_id="clinic-a")
    version = SimpleNamespace(
        id="version-x",
        entry_id="entry-x",
        version=2,
        content="Synthetic clinician evidence",
        content_hash="b" * 64,
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    entry = SimpleNamespace(
        id="entry-x",
        clinic_id="clinic-a",
        title="Clinician source",
        entry_type="clinician_note",
        owner_role="clinician",
        trust_state="clinician_confirmed",
        author_id="user-x",
        current_version_id="version-current",
    )
    author = SimpleNamespace(id="user-x", display_name="Alex Morgan", role="clinician")

    def available(model, identifier):
        return {
            (EntryVersion, "version-x"): version,
            (Entry, "entry-x"): entry,
            (User, "user-x"): author,
        }[(model, identifier)]

    evidence = _source_evidence(SimpleNamespace(get=available), conflict, "version-x")
    assert evidence["author"] == {
        "id": "user-x",
        "display_name": "Alex Morgan",
        "role": "clinician",
    }
    assert evidence["source_is_current"] is False
    assert set(evidence) == {
        "state",
        "entry_id",
        "entry_title",
        "entry_type",
        "owner_role",
        "trust_state",
        "author",
        "version_id",
        "version",
        "content",
        "content_hash",
        "source_is_current",
        "created_at",
    }


def test_conflict_serializer_uses_first_separator_and_normalizes_naive_utc() -> None:
    conflict = SimpleNamespace(
        id="conflict-x",
        clinic_id="clinic-a",
        conflict_type="medication_dose_mismatch",
        summary="Synthetic dose conflict",
        status="resolved",
        disposition="confirm_left|first source|additional rationale",
        resolved_by="user-x",
        left_version_id="missing-left",
        right_version_id="missing-right",
        created_at=datetime(2026, 9, 5, 4, 5, 6),
    )
    serialized = serialize_conflict(SimpleNamespace(get=lambda *_args: None), conflict)
    assert serialized == {
        "id": "conflict-x",
        "conflict_type": "medication_dose_mismatch",
        "summary": "Synthetic dose conflict",
        "status": "resolved",
        "disposition": "confirm_left|first source|additional rationale",
        "resolution": {
            "decision": "confirm_left",
            "rationale": "first source|additional rationale",
            "resolved_by": "user-x",
        },
        "left": {"state": "unavailable", "version_id": "missing-left"},
        "right": {"state": "unavailable", "version_id": "missing-right"},
        "decision_policy": (
            "No automatic winner: preserve both immutable assertions and require clinician "
            "source review or explicit escalation."
        ),
        "created_at": "2026-09-05T04:05:06+00:00",
    }


def test_allergy_parser_continues_after_negative_and_irrelevant_sentences() -> None:
    positives, denies = _allergy_assertions(
        "No known drug allergies. Routine review completed. "
        "Penicillin caused facial swelling. Latex rash documented."
    )
    assert positives == {"penicillin", "latex"}
    assert denies is True


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
