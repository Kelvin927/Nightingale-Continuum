from __future__ import annotations

from .conftest import auth, entry_named, workspace


def test_different_role_owned_sections_do_not_overwrite_each_other(client, identities, patient_id):
    snapshot = workspace(client, identities["clinician"], patient_id)
    staff_entry = entry_named(snapshot, "Follow-up coordination")
    clinician_entry = entry_named(snapshot, "Assessment and plan")

    staff_result = client.patch(
        f"/api/v1/entries/{staff_entry['id']}",
        headers=auth(identities["staff"]),
        json={
            "content": staff_entry["version"]["content"] + "\nCallback queued.",
            "expected_version": 1,
            "reason": "Queue callback",
        },
    )
    clinician_result = client.patch(
        f"/api/v1/entries/{clinician_entry['id']}",
        headers=auth(identities["clinician"]),
        json={
            "content": clinician_entry["version"]["content"] + "\nReview after results.",
            "expected_version": 1,
            "reason": "Clarify review plan",
        },
    )
    assert staff_result.status_code == 200
    assert clinician_result.status_code == 200

    final = workspace(client, identities["clinician"], patient_id)
    assert "Callback queued" in entry_named(final, "Follow-up coordination")["version"]["content"]
    assert "Review after results" in entry_named(final, "Assessment and plan")["version"]["content"]


def test_same_section_stale_write_has_deterministic_conflict(client, identities, patient_id):
    entry = entry_named(
        workspace(client, identities["staff"], patient_id), "Follow-up coordination"
    )
    first = client.patch(
        f"/api/v1/entries/{entry['id']}",
        headers=auth(identities["staff"]),
        json={
            "content": entry["version"]["content"] + "\nFirst concurrent change.",
            "expected_version": 1,
            "reason": "First concurrent writer",
        },
    )
    second = client.patch(
        f"/api/v1/entries/{entry['id']}",
        headers=auth(identities["staff"]),
        json={
            "content": entry["version"]["content"] + "\nSecond concurrent change.",
            "expected_version": 1,
            "reason": "Second concurrent writer",
        },
    )
    assert first.status_code == 200
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "version_conflict"
    assert detail["expected_version"] == 1
    assert detail["current_version"] == 2
    assert detail["resolution"].startswith("Reload")
