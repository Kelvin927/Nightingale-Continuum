from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

import app.main as main_module
from app.capture import (
    CaptureContractError,
    add_segment,
    finalize_capture,
    review_safety_signal,
    start_capture,
)
from app.care import current_version
from app.models import (
    ClinicConfigVersion,
    Entry,
    Patient,
    SafetySignal,
    TranscriptSegment,
    User,
)
from app.schemas import StreamSegmentRequest
from app.scribe import RedactionFidelityError
from app.seed import OTHER_PATIENT_ID, PRIMARY_PATIENT_ID

from .conftest import auth


def segment_payload(
    *,
    text: str = "Patient is allergic to penicillin and takes lisinopril 20 mg.",
    sequence: int = 1,
    chunk_id: str = "chunk-001",
    language_tag: str = "en-SG",
    language_confidence: float = 0.96,
    asr_confidence: float = 0.94,
    audio_quality: float = 0.91,
    speaker_label: str = "patient",
    correction_of_segment_id: str | None = None,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "sequence": sequence,
        "start_ms": (sequence - 1) * 2_000,
        "end_ms": sequence * 2_000,
        "speaker_label": speaker_label,
        "text": text,
        "language_spans": [
            {
                "language_tag": language_tag,
                "start_offset": 0,
                "end_offset": len(text),
                "confidence": language_confidence,
            }
        ],
        "asr_confidence": asr_confidence,
        "audio_quality": audio_quality,
        "correction_of_segment_id": correction_of_segment_id,
    }


def start(client, user_id: str, interaction_type: str = "doctor_consult") -> dict:
    response = client.post(
        f"/api/v1/patients/{PRIMARY_PATIENT_ID}/captures",
        headers=auth(user_id),
        json={"interaction_type": interaction_type},
    )
    assert response.status_code == 201, response.text
    return response.json()


def append(client, user_id: str, capture_id: str, payload: dict):
    return client.post(
        f"/api/v1/captures/{capture_id}/segments",
        headers=auth(user_id),
        json=payload,
    )


def test_trilingual_stream_abstains_on_hokkien_but_surfaces_allergy_immediately(
    client, app, identities
) -> None:
    capture = start(client, identities["clinician"])
    assert capture["status"] == "streaming"
    assert capture["capabilities"]["audio_transcription_active"] is False
    assert capture["capabilities"]["unsupported_language_policy"].startswith("abstain")
    assert capture["assurance_boundary"].startswith("This prototype ingests synthetic")

    text = "Saya allergic to penicillin, bo pian."
    english_start = text.index(" allergic")
    hokkien_start = text.index("bo pian")
    payload = segment_payload(text=text)
    payload["start_ms"] = 120_000
    payload["end_ms"] = 123_000
    payload["language_spans"] = [
        {
            "language_tag": "ms-SG",
            "start_offset": 0,
            "end_offset": english_start,
            "confidence": 0.93,
        },
        {
            "language_tag": "en-SG",
            "start_offset": english_start,
            "end_offset": hokkien_start,
            "confidence": 0.96,
        },
        {
            "language_tag": "nan",
            "start_offset": hokkien_start,
            "end_offset": len(text),
            "confidence": 0.84,
        },
    ]
    response = append(client, identities["clinician"], capture["id"], payload)
    assert response.status_code == 201, response.text
    streamed = response.json()
    assert streamed["segments"][0]["processing_state"] == "abstained"
    assert streamed["segments"][0]["processing_reasons"] == ["unsupported_provider_language:nan"]
    assert streamed["segments"][0]["start_ms"] == 120_000
    assert streamed["ingestion"]["replayed"] is False
    assert streamed["ingestion"]["server_processing_ms"] >= 0
    assert streamed["ingestion"]["latency_scope"].startswith("API processing only")

    [signal] = streamed["safety_signals"]
    assert signal["signal_type"] == "allergy_mention"
    assert signal["normalized_label"] == "penicillin"
    assert signal["severity"] == "critical"
    assert signal["review_state"] == "provisional"
    assert signal["evidence_quote"] == "allergic to penicillin"

    patient_view = client.get(
        f"/api/v1/captures/{capture['id']}",
        headers=auth(identities["patient"]),
    )
    assert patient_view.status_code == 200
    assert patient_view.json()["safety_signals"] == []
    assert patient_view.json()["safety_signal_count"] == 1

    concealed = client.get(
        f"/api/v1/captures/{capture['id']}",
        headers=auth(identities["other_clinician"]),
    )
    assert concealed.status_code == 404

    reviewed = client.post(
        f"/api/v1/safety-signals/{signal['id']}/review",
        headers=auth(identities["clinician"]),
        json={"decision": "confirm", "rationale": "Confirmed directly with patient."},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_state"] == "confirmed"
    assert reviewed.json()["reviewed_by"] == identities["clinician"]

    duplicate_review = client.post(
        f"/api/v1/safety-signals/{signal['id']}/review",
        headers=auth(identities["clinician"]),
        json={"decision": "dismiss", "rationale": "Trying a second decision."},
    )
    assert duplicate_review.status_code == 409
    assert duplicate_review.json()["detail"]["code"] == "signal_not_reviewable"

    finalized = client.post(
        f"/api/v1/captures/{capture['id']}/finalize",
        headers=auth(identities["clinician"]),
    )
    assert finalized.status_code == 200, finalized.text
    final_body = finalized.json()
    assert final_body["status"] == "finalized_with_abstention"
    assert final_body["provider_status"] == "live"
    assert final_body["segments"][0]["status"] == "final"
    assert final_body["finalization"]["replayed"] is False

    entry_id = final_body["finalized_entry_id"]
    with app.state.database.session() as session:
        entry = session.get(Entry, entry_id)
        assert entry is not None
        version = current_version(session, entry)
        assert "bo pian" not in version.content
        assert "UNSUPPORTED LANGUAGE nan" in version.content
    provider_text = app.state.scribe_provider.last_received_text
    assert provider_text is not None
    assert "bo pian" not in provider_text
    assert "UNSUPPORTED LANGUAGE nan" in provider_text

    replay = client.post(
        f"/api/v1/captures/{capture['id']}/finalize",
        headers=auth(identities["clinician"]),
    )
    assert replay.status_code == 200
    assert replay.json()["finalization"] == {"replayed": True, "entry_id": entry_id}

    closed = append(
        client,
        identities["clinician"],
        capture["id"],
        segment_payload(sequence=2, chunk_id="chunk-002"),
    )
    assert closed.status_code == 409
    assert closed.json()["detail"]["code"] == "capture_not_streaming"


def test_correction_retracts_old_segment_and_signal_without_rewriting_history(
    client, app, identities
) -> None:
    capture = start(client, identities["clinician"])
    first = append(
        client,
        identities["clinician"],
        capture["id"],
        segment_payload(text="I am allergic to penicillin."),
    )
    old_segment = first.json()["segments"][0]
    old_signal = first.json()["safety_signals"][0]

    correction_payload = segment_payload(
        text="I am not allergic to penicillin.",
        sequence=2,
        chunk_id="chunk-correction",
        correction_of_segment_id=old_segment["id"],
    )
    corrected = append(
        client,
        identities["clinician"],
        capture["id"],
        correction_payload,
    )
    assert corrected.status_code == 201
    body = corrected.json()
    assert [(item["sequence"], item["status"]) for item in body["segments"]] == [
        (1, "retracted"),
        (2, "provisional"),
    ]
    assert body["segments"][1]["correction_of_segment_id"] == old_segment["id"]
    assert body["safety_signals"][0]["id"] == old_signal["id"]
    assert body["safety_signals"][0]["review_state"] == "source_retracted"
    assert body["ingestion"]["new_safety_signal_ids"] == []

    with app.state.database.session() as session:
        immutable_old = session.get(TranscriptSegment, old_segment["id"])
        assert immutable_old is not None
        assert immutable_old.verbatim_text == "I am allergic to penicillin."

    invalid_again = append(
        client,
        identities["clinician"],
        capture["id"],
        segment_payload(
            text="A second correction.",
            sequence=3,
            chunk_id="chunk-correction-2",
            correction_of_segment_id=old_segment["id"],
        ),
    )
    assert invalid_again.status_code == 409
    assert invalid_again.json()["detail"]["code"] == "invalid_segment_correction"


def test_segment_sequence_idempotency_and_processing_states(client, identities) -> None:
    capture = start(client, identities["clinician"])
    out_of_order = append(
        client,
        identities["clinician"],
        capture["id"],
        segment_payload(sequence=2, chunk_id="chunk-late"),
    )
    assert out_of_order.status_code == 409
    assert out_of_order.json()["detail"]["code"] == "segment_sequence_conflict"
    assert "Expected sequence 1" in out_of_order.json()["detail"]["message"]

    payload = segment_payload(speaker_label="overlap", language_confidence=0.7)
    accepted = append(client, identities["clinician"], capture["id"], payload)
    assert accepted.status_code == 201
    assert accepted.json()["segments"][0]["processing_state"] == "human_review_required"
    assert accepted.json()["segments"][0]["processing_reasons"] == [
        "low_language_confidence:en-sg",
        "speaker_overlap",
    ]

    replay = append(client, identities["clinician"], capture["id"], payload)
    assert replay.status_code == 201
    assert replay.json()["ingestion"]["replayed"] is True
    assert len(replay.json()["segments"]) == 1

    collision_payload = {**payload, "text": "Different content for the same key."}
    collision_payload["language_spans"] = [
        {
            "language_tag": "en-SG",
            "start_offset": 0,
            "end_offset": len(collision_payload["text"]),
            "confidence": 0.7,
        }
    ]
    collision = append(
        client,
        identities["clinician"],
        capture["id"],
        collision_payload,
    )
    assert collision.status_code == 409
    assert collision.json()["detail"]["code"] == "segment_idempotency_collision"


@pytest.mark.parametrize(
    ("changes", "expected_state", "expected_reason"),
    [
        ({"language_tag": "nan"}, "abstained", "unsupported_provider_language:nan"),
        (
            {"language_tag": "en-AU"},
            "supported",
            None,
        ),
        (
            {"language_confidence": 0.5},
            "abstained",
            "very_low_language_confidence:en-sg",
        ),
        ({"asr_confidence": 0.7}, "human_review_required", "low_asr_confidence"),
        ({"asr_confidence": 0.5}, "abstained", "very_low_asr_confidence"),
        ({"audio_quality": 0.6}, "human_review_required", "low_audio_quality"),
        ({"audio_quality": 0.4}, "abstained", "very_low_audio_quality"),
        ({"speaker_label": "unknown"}, "human_review_required", "speaker_unknown"),
    ],
)
def test_quality_and_language_thresholds_are_deterministic(
    client, identities, changes, expected_state, expected_reason
) -> None:
    capture = start(client, identities["clinician"])
    response = append(
        client,
        identities["clinician"],
        capture["id"],
        segment_payload(**changes),
    )
    assert response.status_code == 201
    [segment] = response.json()["segments"]
    assert segment["processing_state"] == expected_state
    if expected_reason is None:
        assert segment["processing_reasons"] == []
    else:
        assert expected_reason in segment["processing_reasons"]


@pytest.mark.parametrize(
    ("payload_change", "message"),
    [
        ({"end_ms": 0}, "greater than 0"),
        ({"start_ms": 3_000, "end_ms": 2_000}, "greater than start_ms"),
        (
            {
                "text": "short",
                "language_spans": [
                    {
                        "language_tag": "en-SG",
                        "start_offset": 0,
                        "end_offset": 99,
                        "confidence": 0.9,
                    }
                ],
            },
            "exceeds transcript",
        ),
        (
            {
                "text": "overlap",
                "language_spans": [
                    {
                        "language_tag": "en-SG",
                        "start_offset": 0,
                        "end_offset": 5,
                        "confidence": 0.9,
                    },
                    {
                        "language_tag": "ms-SG",
                        "start_offset": 4,
                        "end_offset": 7,
                        "confidence": 0.9,
                    },
                ],
            },
            "non-overlapping",
        ),
        (
            {
                "text": "bad",
                "language_spans": [
                    {
                        "language_tag": "en-SG",
                        "start_offset": 2,
                        "end_offset": 1,
                        "confidence": 0.9,
                    }
                ],
            },
            "positive width",
        ),
    ],
)
def test_stream_segment_schema_rejects_invalid_timing_and_offsets(payload_change, message) -> None:
    payload = segment_payload()
    payload.update(payload_change)
    with pytest.raises(ValidationError, match=message):
        StreamSegmentRequest.model_validate(payload)


def test_start_capture_enforces_role_scope_configuration_and_feature(app, identities) -> None:
    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        patient_actor = session.get(User, identities["patient"])
        admin = session.get(User, identities["admin"])
        patient = session.get(Patient, PRIMARY_PATIENT_ID)
        other_patient = session.get(Patient, OTHER_PATIENT_ID)
        assert all(
            item is not None for item in (clinician, patient_actor, admin, patient, other_patient)
        )

        with pytest.raises(CaptureContractError, match="outside actor clinic"):
            start_capture(
                session,
                actor=clinician,
                patient=other_patient,
                interaction_type="doctor_consult",
            )
        with pytest.raises(CaptureContractError, match="cannot start"):
            start_capture(
                session,
                actor=admin,
                patient=patient,
                interaction_type="doctor_consult",
            )
        with pytest.raises(CaptureContractError, match="patient-session"):
            start_capture(
                session,
                actor=patient_actor,
                patient=patient,
                interaction_type="doctor_consult",
            )

        config = session.scalar(
            select(ClinicConfigVersion).where(
                ClinicConfigVersion.clinic_id == clinician.clinic_id,
                ClinicConfigVersion.status == "active",
            )
        )
        assert config is not None
        config.status = "superseded"
        session.flush()
        with pytest.raises(CaptureContractError, match="No active"):
            start_capture(
                session,
                actor=clinician,
                patient=patient,
                interaction_type="doctor_consult",
            )

        config.status = "active"
        changed = dict(config.configuration)
        changed["features"] = {**changed["features"], "streaming_capture": False}
        config.configuration = changed
        session.flush()
        with pytest.raises(CaptureContractError, match="disabled"):
            start_capture(
                session,
                actor=clinician,
                patient=patient,
                interaction_type="doctor_consult",
            )


def test_patient_session_is_allowed_but_clinical_signal_details_are_withheld(
    client, identities
) -> None:
    capture = start(client, identities["patient"], interaction_type="patient_session")
    response = append(
        client,
        identities["patient"],
        capture["id"],
        segment_payload(text="I am allergic to penicillin."),
    )
    assert response.status_code == 201
    assert response.json()["safety_signals"] == []
    assert response.json()["safety_signal_count"] == 1

    wrong_scope = client.post(
        f"/api/v1/patients/{PRIMARY_PATIENT_ID}/captures",
        headers=auth(identities["patient"]),
        json={"interaction_type": "doctor_consult"},
    )
    assert wrong_scope.status_code == 409
    assert wrong_scope.json()["detail"]["code"] == "patient_capture_scope"


def test_clinic_specific_language_policy_can_abstain_on_provider_supported_language(
    client, identities
) -> None:
    started = client.post(
        f"/api/v1/patients/{OTHER_PATIENT_ID}/captures",
        headers=auth(identities["other_clinician"]),
        json={"interaction_type": "doctor_consult"},
    )
    assert started.status_code == 201
    response = append(
        client,
        identities["other_clinician"],
        started.json()["id"],
        segment_payload(text="Saya pening.", language_tag="ms-SG"),
    )
    assert response.status_code == 201
    [segment] = response.json()["segments"]
    assert segment["processing_state"] == "abstained"
    assert segment["processing_reasons"] == ["language_not_enabled_for_clinic:ms-sg"]


def test_finalize_failure_paths_and_missing_objects_are_explicit(
    client, app, identities, monkeypatch
) -> None:
    missing_get = client.get(
        "/api/v1/captures/missing-capture",
        headers=auth(identities["clinician"]),
    )
    missing_segment = append(
        client,
        identities["clinician"],
        "missing-capture",
        segment_payload(),
    )
    missing_finalize = client.post(
        "/api/v1/captures/missing-capture/finalize",
        headers=auth(identities["clinician"]),
    )
    missing_signal = client.post(
        "/api/v1/safety-signals/missing-signal/review",
        headers=auth(identities["clinician"]),
        json={"decision": "confirm", "rationale": "Checked source evidence."},
    )
    missing_responses = (missing_get, missing_segment, missing_finalize, missing_signal)
    assert {item.status_code for item in missing_responses} == {404}

    empty = start(client, identities["clinician"])
    empty_final = client.post(
        f"/api/v1/captures/{empty['id']}/finalize",
        headers=auth(identities["clinician"]),
    )
    assert empty_final.status_code == 409
    assert empty_final.json()["detail"]["code"] == "capture_has_no_segments"

    redaction_capture = start(client, identities["clinician"])
    assert (
        append(
            client,
            identities["clinician"],
            redaction_capture["id"],
            segment_payload(),
        ).status_code
        == 201
    )

    def fail_redaction(*_args, **_kwargs):
        raise RedactionFidelityError("synthetic test failure")

    monkeypatch.setattr(main_module, "finalize_capture", fail_redaction)
    withheld = client.post(
        f"/api/v1/captures/{redaction_capture['id']}/finalize",
        headers=auth(identities["clinician"]),
    )
    assert withheld.status_code == 422
    assert withheld.json()["detail"]["code"] == "redaction_fidelity_failed"


def test_finalize_without_system_actor_fails_closed(client, app, identities) -> None:
    capture = start(client, identities["clinician"])
    assert (
        append(client, identities["clinician"], capture["id"], segment_payload()).status_code == 201
    )
    with app.state.database.session() as session:
        system = session.get(User, identities["system"])
        assert system is not None
        system.role = "retired"
        session.commit()
    response = client.post(
        f"/api/v1/captures/{capture['id']}/finalize",
        headers=auth(identities["clinician"]),
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "System author unavailable"


def test_direct_state_guards_cover_cross_scope_write_review_and_corrupt_link(
    app, identities
) -> None:
    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        patient_actor = session.get(User, identities["patient"])
        other_actor = session.get(User, identities["other_clinician"])
        patient = session.get(Patient, PRIMARY_PATIENT_ID)
        system = session.get(User, identities["system"])
        assert all(
            item is not None for item in (clinician, patient_actor, other_actor, patient, system)
        )
        capture = start_capture(
            session,
            actor=clinician,
            patient=patient,
            interaction_type="doctor_consult",
        )
        payload = StreamSegmentRequest.model_validate(segment_payload())

        with pytest.raises(CaptureContractError, match="outside actor clinic"):
            add_segment(session, actor=other_actor, capture=capture, payload=payload)
        with pytest.raises(CaptureContractError, match="cannot append"):
            add_segment(session, actor=patient_actor, capture=capture, payload=payload)

        capture.status = "abandoned"
        with pytest.raises(CaptureContractError, match="no longer streaming"):
            add_segment(session, actor=clinician, capture=capture, payload=payload)
        with pytest.raises(CaptureContractError, match="no longer streaming"):
            finalize_capture(
                session,
                actor=clinician,
                system_actor=system,
                patient=patient,
                capture=capture,
                provider=app.state.scribe_gateway,
            )
        capture.status = "streaming"
        with pytest.raises(CaptureContractError, match="cannot finalize"):
            finalize_capture(
                session,
                actor=patient_actor,
                system_actor=system,
                patient=patient,
                capture=capture,
                provider=app.state.scribe_gateway,
            )
        with pytest.raises(CaptureContractError, match="outside actor clinic"):
            finalize_capture(
                session,
                actor=other_actor,
                system_actor=system,
                patient=patient,
                capture=capture,
                provider=app.state.scribe_gateway,
            )

        segment = add_segment(session, actor=clinician, capture=capture, payload=payload).segment
        signal = session.scalar(
            select(SafetySignal).where(SafetySignal.source_segment_id == segment.id)
        )
        assert signal is not None
        with pytest.raises(CaptureContractError, match="outside actor clinic"):
            review_safety_signal(
                session,
                actor=other_actor,
                signal=signal,
                decision="confirm",
                rationale="Cross-clinic attempt",
            )
        with pytest.raises(CaptureContractError, match="Only a clinician"):
            review_safety_signal(
                session,
                actor=patient_actor,
                signal=signal,
                decision="confirm",
                rationale="Patient cannot confirm",
            )
        with pytest.raises(CaptureContractError, match="Unknown review"):
            review_safety_signal(
                session,
                actor=clinician,
                signal=signal,
                decision="unknown",
                rationale="Invalid direct call",
            )

    fake_capture = SimpleNamespace(
        clinic_id="clinic",
        finalized_entry_id="missing-entry",
    )
    fake_actor = SimpleNamespace(clinic_id="clinic")
    fake_patient = SimpleNamespace(clinic_id="clinic")
    fake_session = SimpleNamespace(get=lambda *_args: None)
    with pytest.raises(CaptureContractError, match="missing entry"):
        finalize_capture(
            fake_session,
            actor=fake_actor,
            system_actor=SimpleNamespace(),
            patient=fake_patient,
            capture=fake_capture,
            provider=SimpleNamespace(),
        )


def test_supported_and_low_quality_finalization_render_distinct_warnings(
    client, app, identities
) -> None:
    supported = start(client, identities["clinician"])
    response = append(
        client,
        identities["clinician"],
        supported["id"],
        segment_payload(text="Routine follow-up is planned."),
    )
    assert response.json()["segments"][0]["processing_state"] == "supported"
    finished = client.post(
        f"/api/v1/captures/{supported['id']}/finalize",
        headers=auth(identities["clinician"]),
    )
    assert finished.json()["status"] == "finalized"
    assert "Routine follow-up" in app.state.scribe_provider.last_received_text

    review = start(client, identities["clinician"])
    append(
        client,
        identities["clinician"],
        review["id"],
        segment_payload(
            text="Uncertain but audible segment.",
            asr_confidence=0.7,
            sequence=1,
            chunk_id="review-001",
        ),
    )
    client.post(
        f"/api/v1/captures/{review['id']}/finalize",
        headers=auth(identities["clinician"]),
    )
    assert "LOW-CONFIDENCE SEGMENT" in app.state.scribe_provider.last_received_text

    low_quality = start(client, identities["clinician"])
    append(
        client,
        identities["clinician"],
        low_quality["id"],
        segment_payload(
            text="Unreliable audio.",
            audio_quality=0.4,
            sequence=1,
            chunk_id="low-quality-001",
        ),
    )
    client.post(
        f"/api/v1/captures/{low_quality['id']}/finalize",
        headers=auth(identities["clinician"]),
    )
    assert "LOW-QUALITY SEGMENT" in app.state.scribe_provider.last_received_text


def test_staff_can_stream_and_dismiss_signal_but_cannot_clinically_review(
    client, identities
) -> None:
    capture = start(client, identities["staff"], interaction_type="nurse_consult")
    streamed = append(
        client,
        identities["staff"],
        capture["id"],
        segment_payload(text="I am allergic to penicillin."),
    )
    signal_id = streamed.json()["safety_signals"][0]["id"]
    denied = client.post(
        f"/api/v1/safety-signals/{signal_id}/review",
        headers=auth(identities["staff"]),
        json={"decision": "dismiss", "rationale": "Staff review attempt."},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "clinician_confirmation_required"

    dismissed = client.post(
        f"/api/v1/safety-signals/{signal_id}/review",
        headers=auth(identities["clinician"]),
        json={"decision": "dismiss", "rationale": "Clinician checked source audio."},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["review_state"] == "dismissed"
