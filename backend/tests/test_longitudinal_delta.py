from __future__ import annotations

from .conftest import auth


def test_delta_lens_describes_change_without_causal_overclaim(client, identities, patient_id):
    response = client.get(
        f"/api/v1/patients/{patient_id}/delta",
        headers=auth(identities["clinician"]),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["interpretation"] == "temporal_description_not_causal_effect"
    assert "temporal order alone is insufficient" in payload["causal_guardrail"]
    assert any("10 mg to 20 mg" in item["label"] for item in payload["changed_or_conflicting"])
    assert any("Dizziness" in item["label"] for item in payload["new"])
    evidence_items = payload["new"] + payload["changed_or_conflicting"] + payload["persistent"]
    assert any(item.get("evidence", {}).get("provenance_span_id") for item in evidence_items)


def test_patient_cannot_access_internal_delta_lens(client, identities, patient_id):
    response = client.get(
        f"/api/v1/patients/{patient_id}/delta",
        headers=auth(identities["patient"]),
    )
    assert response.status_code == 404
