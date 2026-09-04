from __future__ import annotations

from sqlalchemy import select

from app.models import AuditEvent, OutboundDelivery
from app.seed import PRIMARY_CONTACT_ID
from app.terminology import ADAPTER_VERSION, POLICY_VERSION, assess_medication_terminology

from .conftest import auth, workspace


def test_structured_receipt_normalizes_units_offsets_and_semantic_contrast() -> None:
    text = (
        "Correction: lisinopril changed from 20.00 MG to 10 mg. "
        "Metformin 0.5 g, insulin 4 units, amlodipine 5 mL, "
        "warfarin 8 mcg, amoxicillin 9 ug, and penicillin 7 µg."
    )
    result = assess_medication_terminology(text)

    assert result["policy_version"] == POLICY_VERSION
    assert result["adapter"]["version"] == ADAPTER_VERSION
    assert result["status"] == "structured_review_ready"
    assert result["dose_sensitive"] is True
    assert result["human_confirmation_required"] is True
    assert result["semantic_review_required"] is True
    assert result["release_permitted_after_confirmation"] is True
    assert result["external_reference_performed"] is False
    assert [item["normalized_name"] for item in result["medication_mentions"]] == [
        "lisinopril",
        "metformin",
        "insulin",
        "amlodipine",
        "warfarin",
        "amoxicillin",
        "penicillin",
    ]
    assert [
        (item["normalized_value"], item["normalized_unit"], item["medication_name"])
        for item in result["dose_mentions"]
    ] == [
        ("20", "mg", "lisinopril"),
        ("10", "mg", "lisinopril"),
        ("0.5", "g", "metformin"),
        ("4", "{unit}", "insulin"),
        ("5", "mL", "amlodipine"),
        ("8", "ug", "warfarin"),
        ("9", "ug", "amoxicillin"),
        ("7", "ug", "penicillin"),
    ]
    for mention in [*result["medication_mentions"], *result["dose_mentions"]]:
        assert text[mention["source_start"] : mention["source_end"]] == mention["source_text"]
    assert result["unresolved"] == []
    assert "does not establish prescription accuracy" in result["decision_boundary"]
    assert result["adapter"]["mode"] == "synthetic_rehearsal_only"
    assert "rxnav.nlm.nih.gov" in result["adapter"]["production_endpoint_pattern"]


def test_reverse_order_pairing_and_human_only_or_absent_states() -> None:
    reverse = assess_medication_terminology("Take 20 mg LISINOPRIL now")
    assert reverse["dose_mentions"][0]["medication_name"] == "lisinopril"
    assert reverse["semantic_review_required"] is False

    named_without_dose = assess_medication_terminology("Continue metformin as reviewed.")
    assert named_without_dose["status"] == "human_review_only"
    assert named_without_dose["release_permitted_after_confirmation"] is True

    generic_only = assess_medication_terminology("The medication plan was reviewed.")
    assert generic_only["status"] == "human_review_only"
    assert generic_only["medication_mentions"] == []

    absent = assess_medication_terminology("Your next visit is Monday")
    assert absent["status"] == "not_applicable"
    assert absent["human_confirmation_required"] is False
    assert absent["semantic_review_required"] is False


def test_unlinked_non_positive_distant_and_unsupported_doses_fail_closed() -> None:
    text = (
        "Amlodipine was discussed. 0 mg was written separately. "
        f"Metformin {'context ' * 10}25 mg. "
        f"30 mg {'context ' * 5}warfarin. "
        "Amoxicillin 500 milligrams."
    )
    result = assess_medication_terminology(text)

    assert result["status"] == "blocked_unresolved"
    assert result["release_permitted_after_confirmation"] is False
    assert [item["code"] for item in result["unresolved"]] == [
        "unlinked_dose",
        "non_positive_dose",
        "unlinked_dose",
        "unlinked_dose",
        "unsupported_dose_unit",
    ]
    assert all(
        text[item["source_start"] : item["source_end"]] == item["source_text"]
        for item in result["unresolved"]
    )


def test_delivery_gate_exposes_current_evidence_and_freezes_it_in_approval_receipt(
    client, app, identities, patient_id
) -> None:
    current = next(
        entry
        for entry in workspace(client, identities["clinician"], patient_id)["entries"]
        if entry["entry_type"] == "patient_summary"
    )
    content = "Take lisinopril 10 mg daily, not 20 mg. Call the clinic if uncertain."
    edited = client.patch(
        f"/api/v1/entries/{current['id']}",
        headers=auth(identities["clinician"]),
        json={
            "content": content,
            "expected_version": current["current_version"],
            "reason": "Create a dose-sensitive delivery gate test",
        },
    ).json()
    readiness = client.get(
        f"/api/v1/patients/{patient_id}/delivery-readiness",
        headers=auth(identities["clinician"]),
    ).json()
    assessment = next(
        item for item in readiness["terminology_assessments"] if item["entry_id"] == current["id"]
    )
    assert assessment["source_version_id"] == edited["version"]["id"]
    assert assessment["current_version"] == edited["current_version"]
    assert assessment["status"] == "structured_review_ready"
    assert assessment["semantic_review_required"] is True

    payload = {
        "contact_id": PRIMARY_CONTACT_ID,
        "expected_version": edited["current_version"],
        "idempotency_key": "terminology-receipt",
        "confirm_clinical_review": True,
        "confirm_patient_identity": True,
        "confirm_medication_and_dose": False,
    }
    missing_human_confirmation = client.post(
        f"/api/v1/entries/{current['id']}/deliveries",
        headers=auth(identities["clinician"]),
        json=payload,
    )
    assert missing_human_confirmation.status_code == 409
    assert (
        missing_human_confirmation.json()["detail"]["code"]
        == "medication_dose_attestation_required"
    )

    queued = client.post(
        f"/api/v1/entries/{current['id']}/deliveries",
        headers=auth(identities["clinician"]),
        json={**payload, "confirm_medication_and_dose": True},
    )
    assert queued.status_code == 201
    delivery_payload = queued.json()["deliveries"][0]
    frozen = delivery_payload["approval_evidence"]["terminology"]
    # Queue-time receipts intentionally exclude routing identifiers added by the readiness view.
    expected = {
        key: value
        for key, value in assessment.items()
        if key not in {"entry_id", "source_version_id", "current_version"}
    }
    assert frozen == expected

    with app.state.database.session() as session:
        delivery = session.scalar(
            select(OutboundDelivery).where(OutboundDelivery.id == delivery_payload["id"])
        )
        audit = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.object_id == delivery_payload["id"])
            .order_by(AuditEvent.sequence.desc())
        )
        assert delivery is not None and audit is not None
        assert delivery.approval_evidence["terminology"] == expected
        assert audit.event_metadata["terminology_status"] == "structured_review_ready"

    patient_readiness = client.get(
        f"/api/v1/patients/{patient_id}/delivery-readiness",
        headers=auth(identities["patient"]),
    ).json()
    assert "terminology_assessments" not in patient_readiness
    assert "approval_evidence" not in patient_readiness["deliveries"][0]


def test_delivery_gate_blocks_unlinked_dose_even_with_attestation(
    client, identities, patient_id
) -> None:
    current = next(
        entry
        for entry in workspace(client, identities["clinician"], patient_id)["entries"]
        if entry["entry_type"] == "patient_summary"
    )
    edited = client.patch(
        f"/api/v1/entries/{current['id']}",
        headers=auth(identities["clinician"]),
        json={
            "content": "Take 25 mg tonight.",
            "expected_version": current["current_version"],
            "reason": "Exercise unresolved terminology blocking",
        },
    ).json()
    blocked = client.post(
        f"/api/v1/entries/{current['id']}/deliveries",
        headers=auth(identities["clinician"]),
        json={
            "contact_id": PRIMARY_CONTACT_ID,
            "expected_version": edited["current_version"],
            "idempotency_key": "unlinked-dose-block",
            "confirm_clinical_review": True,
            "confirm_patient_identity": True,
            "confirm_medication_and_dose": True,
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "terminology_release_blocked"
