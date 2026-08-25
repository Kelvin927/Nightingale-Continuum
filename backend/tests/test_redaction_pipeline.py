from __future__ import annotations

from app.models import ProvenanceSpan
from app.redaction import redact_text
from sqlalchemy import select

from .conftest import auth


def test_redactor_removes_required_identifiers_without_returning_values():
    raw = (
        "My name is Maya Chen. NRIC S1234567D. Call +65 9123 4567 or "
        "maya.chen@example.test. Dr Lina Patel adjusted the medication."
    )
    result = redact_text(raw, known_names=["Maya Chen", "Dr Lina Patel"])
    assert "Maya Chen" not in result.text
    assert "S1234567D" not in result.text
    assert "9123 4567" not in result.text
    assert "maya.chen@example.test" not in result.text
    assert result.receipt.entity_counts["PERSON"] >= 2
    assert result.receipt.entity_counts["SG_NRIC_FIN"] == 1
    assert result.receipt.entity_counts["PHONE_NUMBER"] == 1
    assert result.receipt.entity_counts["EMAIL_ADDRESS"] == 1
    assert all(not hasattr(item, "value") for item in result.findings)


def test_provider_boundary_receives_redacted_text_only(client, app, identities, patient_id):
    raw = "Maya Chen, S1234567D, can be reached at +65 9123 4567 about lisinopril 20 mg."
    response = client.post(
        "/api/v1/scribe/ingest",
        headers=auth(identities["clinician"]),
        json={
            "patient_id": patient_id,
            "interaction_type": "doctor_consult",
            "transcript": raw,
            "source_uri": "session://synthetic/privacy-boundary-test",
        },
    )
    assert response.status_code == 201, response.text
    boundary_text = app.state.scribe_provider.last_received_text
    assert boundary_text is not None
    assert "Maya Chen" not in boundary_text
    assert "S1234567D" not in boundary_text
    assert "9123 4567" not in boundary_text
    assert "<PERSON>" in boundary_text
    assert "<SG_NRIC_FIN>" in boundary_text
    assert response.json()["redaction_receipt"]["passed"] is True


def test_patient_voice_can_only_create_patient_session(client, identities, patient_id):
    denied = client.post(
        "/api/v1/scribe/ingest",
        headers=auth(identities["patient"]),
        json={
            "patient_id": patient_id,
            "interaction_type": "doctor_consult",
            "transcript": "Synthetic consult text.",
            "source_uri": "session://synthetic/patient-invalid",
        },
    )
    assert denied.status_code == 403
    accepted = client.post(
        "/api/v1/scribe/ingest",
        headers=auth(identities["patient"]),
        json={
            "patient_id": patient_id,
            "interaction_type": "patient_session",
            "transcript": "Maya Chen reports a pending follow-up.",
            "source_uri": "session://synthetic/patient-valid",
        },
    )
    assert accepted.status_code == 201
    assert accepted.json()["status"] == "submitted_for_human_review"


def test_low_confidence_capture_abstains_without_creating_highlights(
    client, app, identities, patient_id
):
    response = client.post(
        "/api/v1/scribe/ingest",
        headers=auth(identities["clinician"]),
        json={
            "patient_id": patient_id,
            "interaction_type": "doctor_consult",
            "transcript": "[inaudible] dose?",
            "source_uri": "session://synthetic/low-confidence-abstention",
        },
    )
    assert response.status_code == 201, response.text
    assert "low_confidence_abstention" in response.json()["flags"]

    workspace = client.get(
        f"/api/v1/patients/{patient_id}/workspace",
        headers=auth(identities["clinician"]),
    ).json()
    entry = next(item for item in workspace["entries"] if item["id"] == response.json()["entry_id"])
    assert entry["title"].startswith("AI abstention")
    assert "No clinical fact has been asserted" in entry["version"]["content"]
    with app.state.database.session() as session:
        spans = list(
            session.scalars(
                select(ProvenanceSpan).where(ProvenanceSpan.source_entry_id == entry["id"])
            )
        )
        assert spans == []
