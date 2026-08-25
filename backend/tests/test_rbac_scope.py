from __future__ import annotations

from app.seed import OTHER_PATIENT_ID

from .conftest import auth, entry_named, workspace


def test_staff_and_clinician_cannot_write_as_each_other(client, identities, patient_id):
    staff_view = workspace(client, identities["staff"], patient_id)
    clinician_entry = entry_named(staff_view, "Assessment and plan")
    staff_entry = entry_named(staff_view, "Follow-up coordination")

    staff_overwrite = client.patch(
        f"/api/v1/entries/{clinician_entry['id']}",
        headers=auth(identities["staff"]),
        json={
            "content": "Attempted staff overwrite.",
            "expected_version": clinician_entry["current_version"],
            "reason": "Negative authorization test",
        },
    )
    assert staff_overwrite.status_code == 403
    assert staff_overwrite.json()["detail"]["code"] == "cross_role_overwrite_denied"

    clinician_overwrite = client.patch(
        f"/api/v1/entries/{staff_entry['id']}",
        headers=auth(identities["clinician"]),
        json={
            "content": "Attempted clinician overwrite.",
            "expected_version": staff_entry["current_version"],
            "reason": "Negative authorization test",
        },
    )
    assert clinician_overwrite.status_code == 403
    assert clinician_overwrite.json()["detail"]["code"] == "cross_role_overwrite_denied"


def test_patient_cannot_access_internal_comments_or_raw_ai_notes(client, identities, patient_id):
    internal = workspace(client, identities["clinician"], patient_id)
    raw_ai = next(item for item in internal["entries"] if item["entry_type"].startswith("ai_"))
    assert any(item.get("comment_threads") for item in internal["entries"])

    patient = workspace(client, identities["patient"], patient_id)
    assert patient["entries"]
    assert all(not item["entry_type"].startswith("ai_") for item in patient["entries"])
    assert all("comment_threads" not in item for item in patient["entries"])
    assert all(item["visibility"] == "patient" for item in patient["entries"])

    direct_ai_access = client.get(
        f"/api/v1/entries/{raw_ai['id']}/versions",
        headers=auth(identities["patient"]),
    )
    assert direct_ai_access.status_code == 404


def test_cross_clinic_object_ids_are_concealed(client, identities):
    response = client.get(
        f"/api/v1/patients/{OTHER_PATIENT_ID}/workspace",
        headers=auth(identities["clinician"]),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Resource not found"


def test_client_supplied_role_is_ignored(client, identities):
    response = client.get(
        "/api/v1/me?role=clinician",
        headers={**auth(identities["patient"]), "X-Role": "clinician"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "patient"
