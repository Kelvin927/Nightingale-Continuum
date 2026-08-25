from __future__ import annotations

from .conftest import auth


def test_retention_preserves_active_safety_sources(client, identities):
    response = client.post(
        "/api/v1/admin/retention/run",
        headers=auth(identities["admin"]),
        json={"as_of": "2027-08-26T00:00:00+00:00"},
    )
    assert response.status_code == 200, response.text
    changes = response.json()["changes"]
    assert changes
    assert all(item["source_hash"] for item in changes)
    assert all(item["to_tier"] in {"hot", "warm", "cold"} for item in changes)
    # At least one old low-risk record decays while protected active safety evidence stays hot.
    assert any(item["to_tier"] == "cold" for item in changes)


def test_shadow_evaluation_is_explicit_about_insufficient_data(client, identities):
    response = client.get(
        "/api/v1/research/policy-evaluation",
        headers=auth(identities["clinician"]),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_data"
    assert payload["observations"] == 0
    assert payload["doubly_robust_value"] is None
    assert len(payload["assumptions"]) == 4
