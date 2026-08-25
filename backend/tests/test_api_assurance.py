from __future__ import annotations

from sqlalchemy import select

from app.models import GlanceProjection, User

from .conftest import auth, entry_named, workspace


def test_public_metadata_security_headers_and_authentication_fail_closed(client, app, identities):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["synthetic_data_only"] is True
    assert health.headers["cache-control"] == "no-store"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in health.headers["permissions-policy"]

    demo = client.get("/api/v1/demo/identities")
    assert demo.status_code == 200
    assert {item["role"] for item in demo.json()["identities"]} == {
        "admin",
        "clinician",
        "patient",
        "staff",
    }

    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers=auth("missing-user")).status_code == 401

    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        assert actor is not None
        actor.active = False
        session.commit()
    assert client.get("/api/v1/me", headers=auth(identities["clinician"])).status_code == 401


def test_patient_owned_entry_round_trip_and_allow_list_projection(client, identities, patient_id):
    listed = client.get("/api/v1/patients", headers=auth(identities["patient"]))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["patients"]] == [patient_id]

    created = client.post(
        f"/api/v1/patients/{patient_id}/entries",
        headers={**auth(identities["patient"]), "X-Request-ID": "patient-create-1"},
        json={
            "entry_type": "patient_insight",
            "title": "Home observation",
            "content": "I am awaiting a follow-up call about dizziness.",
            "visibility": "patient",
        },
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["owner_role"] == "patient"
    assert "comment_threads" not in entry

    edited = client.patch(
        f"/api/v1/entries/{entry['id']}",
        headers=auth(identities["patient"]),
        json={
            "content": "I am awaiting follow-up and the dizziness has improved.",
            "expected_version": 1,
            "reason": "Clarify home observation",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["current_version"] == 2

    reverted = client.post(
        f"/api/v1/entries/{entry['id']}/revert",
        headers=auth(identities["patient"]),
        json={
            "target_version": 1,
            "expected_version": 2,
            "reason": "Restore patient baseline",
        },
    )
    assert reverted.status_code == 200
    assert reverted.json()["current_version"] == 3

    glance = client.get(
        f"/api/v1/patients/{patient_id}/glance",
        headers=auth(identities["patient"]),
    )
    assert glance.status_code == 200
    assert glance.json()["patient_mode"] is True
    assert any(item["id"] == entry["id"] for item in glance.json()["groups"]["watch"])

    internal = client.post(
        f"/api/v1/patients/{patient_id}/entries",
        headers=auth(identities["patient"]),
        json={
            "entry_type": "patient_insight",
            "title": "Hidden observation",
            "content": "Synthetic text",
            "visibility": "internal",
        },
    )
    assert internal.status_code == 403
    assert internal.json()["detail"]["code"] == "patient_visibility_required"

    wrong_type = client.post(
        f"/api/v1/patients/{patient_id}/entries",
        headers=auth(identities["patient"]),
        json={
            "entry_type": "clinician_note",
            "title": "Wrong role",
            "content": "Synthetic text",
            "visibility": "patient",
        },
    )
    assert wrong_type.status_code == 403
    assert wrong_type.json()["detail"]["code"] == "entry_type_not_permitted"

    admin_create = client.post(
        f"/api/v1/patients/{patient_id}/entries",
        headers=auth(identities["admin"]),
        json={
            "entry_type": "admin_event",
            "title": "Admin content",
            "content": "Synthetic text",
            "visibility": "internal",
        },
    )
    assert admin_create.status_code == 403


def test_clinician_create_edit_diff_and_revert_failure_receipts(client, identities, patient_id):
    created = client.post(
        f"/api/v1/patients/{patient_id}/entries",
        headers={**auth(identities["clinician"]), "X-Request-ID": "clinical-create-1"},
        json={
            "entry_type": "clinician_note",
            "title": "Assurance note",
            "content": "Assessment: blood pressure follow-up remains pending.",
            "visibility": "internal",
        },
    )
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]

    edited = client.patch(
        f"/api/v1/entries/{entry_id}",
        headers={**auth(identities["clinician"]), "X-Request-ID": "clinical-edit-1"},
        json={
            "content": "Assessment: blood pressure follow-up completed; diagnosis unchanged.",
            "expected_version": 1,
            "reason": "Record completed follow-up",
        },
    )
    assert edited.status_code == 200, edited.text

    versions = client.get(
        f"/api/v1/entries/{entry_id}/versions",
        headers=auth(identities["clinician"]),
    )
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()["versions"]] == [2, 1]

    diff = client.get(
        f"/api/v1/entries/{entry_id}/diff?from_version=1&to_version=2",
        headers=auth(identities["clinician"]),
    )
    assert diff.status_code == 200
    assert diff.json()["changes"]

    missing_diff = client.get(
        f"/api/v1/entries/{entry_id}/diff?from_version=1&to_version=99",
        headers=auth(identities["clinician"]),
    )
    assert missing_diff.status_code == 404

    missing_target = client.post(
        f"/api/v1/entries/{entry_id}/revert",
        headers=auth(identities["clinician"]),
        json={"target_version": 99, "expected_version": 2, "reason": "Missing target test"},
    )
    assert missing_target.status_code == 404
    assert missing_target.json()["detail"] == "Target version not found"

    stale = client.post(
        f"/api/v1/entries/{entry_id}/revert",
        headers=auth(identities["clinician"]),
        json={"target_version": 1, "expected_version": 1, "reason": "Stale revert test"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "version_conflict"

    restored = client.post(
        f"/api/v1/entries/{entry_id}/revert",
        headers={**auth(identities["clinician"]), "X-Request-ID": "clinical-revert-1"},
        json={"target_version": 1, "expected_version": 2, "reason": "Restore baseline"},
    )
    assert restored.status_code == 200
    assert restored.json()["current_version"] == 3


def test_comments_mentions_assignment_resolve_reopen_and_invalid_collaborators(
    client, identities, patient_id
):
    clinician_view = workspace(client, identities["clinician"], patient_id)
    entry = entry_named(clinician_view, "Assessment and plan")

    created = client.post(
        f"/api/v1/entries/{entry['id']}/comments",
        headers=auth(identities["clinician"]),
        json={
            "title": "Assurance discussion",
            "body": "Please verify the follow-up owner.",
            "mentions": [identities["staff"]],
            "assigned_to": identities["clinician"],
        },
    )
    assert created.status_code == 201, created.text
    thread_id = created.json()["id"]

    added = client.post(
        f"/api/v1/comment-threads/{thread_id}/comments",
        headers=auth(identities["staff"]),
        json={"body": "Owner confirmed.", "mentions": [], "assigned_to": None},
    )
    assert added.status_code == 201

    resolved = client.post(
        f"/api/v1/comment-threads/{thread_id}/resolve",
        headers=auth(identities["clinician"]),
        json={"resolved": True},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved_by"] == identities["clinician"]

    reopened = client.post(
        f"/api/v1/comment-threads/{thread_id}/resolve",
        headers=auth(identities["staff"]),
        json={"resolved": False},
    )
    assert reopened.status_code == 200
    assert reopened.json()["resolved_by"] is None

    invalid_collaborator = client.post(
        f"/api/v1/entries/{entry['id']}/comments",
        headers=auth(identities["clinician"]),
        json={
            "title": "Invalid assignment",
            "body": "Must fail.",
            "mentions": [identities["patient"]],
            "assigned_to": None,
        },
    )
    assert invalid_collaborator.status_code == 403
    assert invalid_collaborator.json()["detail"]["code"] == "invalid_collaborator"

    missing_collaborator = client.post(
        f"/api/v1/entries/{entry['id']}/comments",
        headers=auth(identities["clinician"]),
        json={
            "title": "Missing collaborator",
            "body": "Must fail.",
            "mentions": ["missing-user"],
            "assigned_to": None,
        },
    )
    assert missing_collaborator.status_code == 403

    assert (
        client.post(
            "/api/v1/comment-threads/missing/comments",
            headers=auth(identities["clinician"]),
            json={"body": "Missing", "mentions": [], "assigned_to": None},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/entries/{entry['id']}/comments",
            headers=auth(identities["patient"]),
            json={"title": "Denied", "body": "Denied", "mentions": []},
        ).status_code
        == 404
    )


def test_admin_research_feedback_and_scribe_denial_paths(client, app, identities, patient_id):
    for path in ("/api/v1/admin/audit/verify", "/api/v1/admin/audit/events"):
        response = client.get(path, headers=auth(identities["clinician"]))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "admin_required"

    verified = client.get("/api/v1/admin/audit/verify", headers=auth(identities["admin"]))
    assert verified.status_code == 200
    assert verified.json()["valid"] is True

    events = client.get("/api/v1/admin/audit/events?limit=3", headers=auth(identities["admin"]))
    assert events.status_code == 200
    assert len(events.json()["events"]) == 3
    assert (
        client.get(
            "/api/v1/admin/audit/events?limit=0", headers=auth(identities["admin"])
        ).status_code
        == 422
    )

    now_retention = client.post(
        "/api/v1/admin/retention/run",
        headers=auth(identities["admin"]),
        json={"as_of": None},
    )
    assert now_retention.status_code == 200

    naive_retention = client.post(
        "/api/v1/admin/retention/run",
        headers=auth(identities["admin"]),
        json={"as_of": "2027-08-26T00:00:00"},
    )
    assert naive_retention.status_code == 200
    assert naive_retention.json()["evaluated_at"].endswith("+00:00")

    projection = client.get(
        f"/api/v1/patients/{patient_id}/glance",
        headers=auth(identities["clinician"]),
    ).json()
    highlight_id = projection["groups"]["act_now"][0]["id"]
    assert (
        client.post(
            f"/api/v1/highlights/{highlight_id}/feedback",
            headers=auth(identities["admin"]),
            json={"action": "accept", "display_propensity": 0.5},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/highlights/missing/feedback",
            headers=auth(identities["clinician"]),
            json={"action": "accept", "display_propensity": 0.5},
        ).status_code
        == 404
    )

    assert (
        client.post(
            "/api/v1/scribe/ingest",
            headers=auth(identities["admin"]),
            json={
                "patient_id": patient_id,
                "interaction_type": "doctor_consult",
                "transcript": "Synthetic consultation with enough words for review.",
                "source_uri": "session://synthetic/admin-denial",
            },
        ).status_code
        == 403
    )

    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        assert clinician is not None
        system_actor = session.scalar(
            select(User).where(User.role == "system", User.clinic_id == clinician.clinic_id)
        )
        assert system_actor is not None
        system_actor.role = "inactive_system"
        session.commit()
    unavailable = client.post(
        "/api/v1/scribe/ingest",
        headers=auth(identities["clinician"]),
        json={
            "patient_id": patient_id,
            "interaction_type": "doctor_consult",
            "transcript": "Synthetic consultation with enough words for review.",
            "source_uri": "session://synthetic/no-system-author",
        },
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == "System author unavailable"


def test_unknown_provenance_and_patient_research_access_are_concealed(
    client, app, identities, patient_id
):
    assert (
        client.get(
            "/api/v1/provenance/missing/resolve",
            headers=auth(identities["clinician"]),
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/v1/research/policy-evaluation",
            headers=auth(identities["patient"]),
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/patients/{patient_id}/workspace",
            headers=auth(identities["staff"]),
        ).status_code
        == 200
    )
    staff_list = client.get("/api/v1/patients", headers=auth(identities["staff"]))
    assert staff_list.status_code == 200
    assert len(staff_list.json()["patients"]) >= 1
    assert (
        client.get(
            "/api/v1/entries/missing/versions",
            headers=auth(identities["clinician"]),
        ).status_code
        == 404
    )

    with app.state.database.session() as session:
        projection = session.get(GlanceProjection, patient_id)
        assert projection is not None
        session.delete(projection)
        session.commit()
    rebuilt = client.get(
        f"/api/v1/patients/{patient_id}/glance",
        headers=auth(identities["clinician"]),
    )
    assert rebuilt.status_code == 200
    assert rebuilt.json()["source_revision"] == 1
