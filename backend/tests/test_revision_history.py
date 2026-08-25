from __future__ import annotations

from .conftest import auth, entry_named, workspace


def test_edit_increments_version_revert_restores_content_and_audit_is_metadata_only(
    client, identities, patient_id
):
    initial = workspace(client, identities["clinician"], patient_id)
    entry = entry_named(initial, "Assessment and plan")
    original_content = entry["version"]["content"]
    revised_content = original_content + "\nReview renal function within 48 hours."

    edited = client.patch(
        f"/api/v1/entries/{entry['id']}",
        headers=auth(identities["clinician"]),
        json={
            "content": revised_content,
            "expected_version": 1,
            "reason": "Clarify review interval",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["current_version"] == 2
    assert edited.json()["version"]["content"] == revised_content

    versions = client.get(
        f"/api/v1/entries/{entry['id']}/versions",
        headers=auth(identities["clinician"]),
    ).json()["versions"]
    assert [item["version"] for item in versions] == [2, 1]

    reverted = client.post(
        f"/api/v1/entries/{entry['id']}/revert",
        headers=auth(identities["clinician"]),
        json={
            "target_version": 1,
            "expected_version": 2,
            "reason": "Restore reviewed baseline",
        },
    )
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["current_version"] == 3
    assert reverted.json()["version"]["content"] == original_content
    assert reverted.json()["version"]["reverted_from_version_id"] is not None

    audit = client.get(
        "/api/v1/admin/audit/events?limit=100",
        headers=auth(identities["admin"]),
    )
    assert audit.status_code == 200
    relevant = [
        item
        for item in audit.json()["events"]
        if item["object_id"] == entry["id"] and item["action"] in {"entry.edited", "entry.reverted"}
    ]
    assert {item["action"] for item in relevant} == {"entry.edited", "entry.reverted"}
    serialized = str(relevant)
    assert revised_content not in serialized
    assert original_content not in serialized
    assert all("from_version" in item["metadata"] for item in relevant)

    verification = client.get(
        "/api/v1/admin/audit/verify",
        headers=auth(identities["admin"]),
    )
    assert verification.status_code == 200
    assert verification.json()["valid"] is True


def test_diff_reports_changed_content(client, identities, patient_id):
    entry = entry_named(
        workspace(client, identities["staff"], patient_id), "Follow-up coordination"
    )
    response = client.patch(
        f"/api/v1/entries/{entry['id']}",
        headers=auth(identities["staff"]),
        json={
            "content": entry["version"]["content"] + "\nPatient callback scheduled for tomorrow.",
            "expected_version": 1,
            "reason": "Add callback schedule",
        },
    )
    assert response.status_code == 200
    diff = client.get(
        f"/api/v1/entries/{entry['id']}/diff?from_version=1&to_version=2",
        headers=auth(identities["staff"]),
    )
    assert diff.status_code == 200
    assert diff.json()["changes"]
    assert "Patient callback scheduled" in str(diff.json()["changes"])
