from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import audit as audit_module
from app import care as care_module
from app import importance as importance_module
from app.audit import (
    GENESIS_HASH,
    AuditVerification,
    _canonical_json,
    append_audit,
    audit_count,
    verify_audit_chain,
)
from app.care import (
    VersionConflictError,
    content_hash,
    create_entry,
    edit_entry,
    revert_entry,
    version_diff,
)
from app.database import Database
from app.evaluation import PolicyEvaluation, _target_probability, evaluate_shadow_policy
from app.importance import (
    _classify_sentence,
    _posterior,
    _update_posterior,
    adaptive_score,
    base_score,
)
from app.models import (
    AuditEvent,
    Clinic,
    Entry,
    EntryVersion,
    FeaturePosterior,
    Highlight,
    ImportanceFeedback,
    Patient,
    ProvenanceSpan,
    User,
)
from app.provenance import create_span, resolve_span
from app.redaction import (
    Finding,
    RedactionReceipt,
    _known_name_findings,
    _normalize_findings,
    redact_text,
)


def test_redaction_contract_is_exact_at_name_boundaries_overlap_and_receipt_version():
    assert _known_name_findings("Li met MAYA CHEN", ["  Li  ", "A", "Maya Chen"]) == [
        Finding("PERSON", 0, 2, 0.99),
        Finding("PERSON", 7, 16, 0.99),
    ]
    assert _normalize_findings(
        [
            Finding("LOW_LONG", 0, 10, 0.7),
            Finding("HIGH_SHORT", 2, 7, 0.9),
            Finding("EQUAL_LONG", 2, 8, 0.9),
            Finding("TOUCHING", 8, 12, 0.5),
            Finding("INVALID", 20, 20, 1.0),
        ]
    ) == [
        Finding("EQUAL_LONG", 2, 8, 0.9),
        Finding("TOUCHING", 8, 12, 0.5),
    ]
    assert _normalize_findings(
        [
            Finding("EARLY_LONG", 0, 10, 0.8),
            Finding("LATE_SHORT", 9, 15, 0.8),
        ]
    ) == [Finding("EARLY_LONG", 0, 10, 0.8)]

    result = redact_text("Call Li at 91234567.", known_names=["Li"])
    assert result.text == "Call <PERSON> at <PHONE_NUMBER>."
    assert result.findings == (
        Finding("PERSON", 5, 7, 0.99),
        Finding("PHONE_NUMBER", 11, 19, 0.96),
    )
    assert result.receipt == RedactionReceipt(
        detector_version="continuum-redactor-v1",
        entity_counts={"PERSON": 1, "PHONE_NUMBER": 1},
        sanitized_sha256="dc5a2435558097427b1bb12626c86cf45b1ed2bbcff33758bc9b33c6a8f33b22",
        clinical_anchor_count=0,
        clinical_anchors_preserved=True,
        passed=True,
    )

    with pytest.raises(ValueError) as error:
        redact_text(" \n ")
    assert error.value.args == ("Text must not be empty",)


def test_audit_canonicalization_append_and_verification_contract_is_exact(monkeypatch):
    timestamp = datetime(2026, 8, 26, 12, 30, tzinfo=UTC)
    assert _canonical_json({"z": 2, "a": timestamp, "nested": {"b": True}}) == (
        '{"a":"2026-08-26 12:30:00+00:00","nested":{"b":true},"z":2}'
    )
    ids = iter(("event-fixed-1", "request-fixed-1", "event-fixed-2", "request-fixed-2"))
    monkeypatch.setattr(audit_module, "new_id", lambda: next(ids))

    database = Database("sqlite://")
    database.create_all()
    with database.session() as session:
        clinic_id = "clinic-contract"
        session.add(Clinic(id=clinic_id, name="Contract Clinic", created_at=timestamp))
        session.flush()
        first = append_audit(
            session,
            clinic_id=clinic_id,
            actor_id=None,
            action="contract.first",
            object_type="synthetic",
            object_id="object-1",
            object_version=3,
            metadata={"safe": True},
            created_at=timestamp,
        )
        second = append_audit(
            session,
            clinic_id=clinic_id,
            actor_id=None,
            action="contract.second",
            object_type="synthetic",
            object_id="object-2",
            created_at=timestamp,
        )
        assert (
            first.id,
            first.sequence,
            first.request_id,
            first.previous_hash,
            first.event_metadata,
            first.object_version,
        ) == (
            "event-fixed-1",
            1,
            "request-fixed-1",
            GENESIS_HASH,
            {"safe": True},
            3,
        )
        assert len(first.event_hash) == 64
        assert second.sequence == first.sequence + 1
        assert second.previous_hash == first.event_hash
        assert second.request_id == "request-fixed-2"
        assert audit_count(session, clinic_id) == 2
        assert verify_audit_chain(session, clinic_id) == AuditVerification(True, 2)
    database.engine.dispose()


def test_care_lifecycle_persists_exact_versions_audit_contract_and_diff(
    app, identities, patient_id, monkeypatch
):
    created_at = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
    edited_at = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    reverted_at = datetime(2026, 8, 26, 11, 0, tzinfo=UTC)

    class FixedDateTime(datetime):
        current = created_at
        calls = []

        @classmethod
        def now(cls, timezone=None):
            cls.calls.append(timezone)
            return cls.current

    monkeypatch.setattr(care_module, "datetime", FixedDateTime)
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        patient = session.get(Patient, patient_id)
        assert actor is not None and patient is not None
        entry = create_entry(
            session,
            actor=actor,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Exact lifecycle contract",
            content="Baseline line.\nRemove this line.",
            visibility="internal",
            trust_state="clinician_confirmed",
            source_uri="session://exact-lifecycle",
            request_id="request-create-exact",
        )
        initial = session.get(EntryVersion, entry.current_version_id)
        assert initial is not None
        assert (
            entry.clinic_id,
            entry.patient_id,
            entry.author_id,
            entry.owner_role,
            entry.entry_type,
            entry.title,
            entry.visibility,
            entry.trust_state,
            entry.source_uri,
            entry.created_at,
            entry.updated_at,
            entry.current_version,
        ) == (
            patient.clinic_id,
            patient.id,
            actor.id,
            "clinician",
            "clinician_note",
            "Exact lifecycle contract",
            "internal",
            "clinician_confirmed",
            "session://exact-lifecycle",
            created_at,
            created_at,
            1,
        )
        assert (
            initial.entry_id,
            initial.version,
            initial.content,
            initial.content_hash,
            initial.created_by,
            initial.change_reason,
            initial.created_at.replace(tzinfo=UTC),
            initial.reverted_from_version_id,
        ) == (
            entry.id,
            1,
            "Baseline line.\nRemove this line.",
            content_hash("Baseline line.\nRemove this line."),
            actor.id,
            "Initial version",
            created_at,
            None,
        )
        created_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.object_id == entry.id,
                AuditEvent.action == "entry.created",
            )
        )
        assert created_event is not None
        assert (
            created_event.actor_id,
            created_event.object_type,
            created_event.object_version,
            created_event.request_id,
            created_event.event_metadata,
            created_event.created_at.replace(tzinfo=UTC),
        ) == (
            actor.id,
            "entry",
            1,
            "request-create-exact",
            {
                "entry_type": "clinician_note",
                "owner_role": "clinician",
                "visibility": "internal",
            },
            created_at,
        )

        FixedDateTime.current = edited_at
        edited = edit_entry(
            session,
            actor=actor,
            entry=entry,
            content="Baseline revised.\nAdded line.",
            expected_version=1,
            reason="Exact edit reason",
            request_id="request-edit-exact",
        )
        assert (
            edited.entry_id,
            edited.version,
            edited.content,
            edited.content_hash,
            edited.created_by,
            edited.change_reason,
            entry.current_version,
            entry.current_version_id,
            entry.updated_at,
        ) == (
            entry.id,
            2,
            "Baseline revised.\nAdded line.",
            content_hash("Baseline revised.\nAdded line."),
            actor.id,
            "Exact edit reason",
            2,
            edited.id,
            edited_at,
        )
        edited_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.object_id == entry.id,
                AuditEvent.action == "entry.edited",
            )
        )
        assert edited_event is not None
        assert (
            edited_event.actor_id,
            edited_event.object_type,
            edited_event.object_version,
            edited_event.request_id,
            edited_event.event_metadata,
        ) == (
            actor.id,
            "entry",
            2,
            "request-edit-exact",
            {"from_version": 1, "to_version": 2},
        )

        FixedDateTime.current = reverted_at
        reverted = revert_entry(
            session,
            actor=actor,
            entry=entry,
            target_version=1,
            expected_version=2,
            reason="Exact revert reason",
            request_id="request-revert-exact",
        )
        assert (
            reverted.entry_id,
            reverted.version,
            reverted.content,
            reverted.content_hash,
            reverted.created_by,
            reverted.change_reason,
            reverted.reverted_from_version_id,
            entry.current_version,
            entry.current_version_id,
            entry.updated_at,
        ) == (
            entry.id,
            3,
            initial.content,
            initial.content_hash,
            actor.id,
            "Exact revert reason",
            initial.id,
            3,
            reverted.id,
            reverted_at,
        )
        reverted_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.object_id == entry.id,
                AuditEvent.action == "entry.reverted",
            )
        )
        assert reverted_event is not None
        assert (
            reverted_event.actor_id,
            reverted_event.object_type,
            reverted_event.object_version,
            reverted_event.request_id,
            reverted_event.event_metadata,
        ) == (
            actor.id,
            "entry",
            3,
            "request-revert-exact",
            {"from_version": 2, "target_version": 1, "to_version": 3},
        )
        assert FixedDateTime.calls == [UTC, UTC, UTC]

        with pytest.raises(VersionConflictError) as edit_conflict:
            edit_entry(
                session,
                actor=actor,
                entry=entry,
                content="Stale edit",
                expected_version=99,
                reason="Stale",
            )
        assert edit_conflict.value.expected_version == 99
        assert edit_conflict.value.current_version == 3
        assert edit_conflict.value.current_version_id == reverted.id
        assert edit_conflict.value.base_snapshot is None
        assert edit_conflict.value.current_snapshot is not None
        assert edit_conflict.value.proposed_content == "Stale edit"
        assert edit_conflict.value.merge_assistance is None

        with pytest.raises(VersionConflictError) as revert_conflict:
            revert_entry(
                session,
                actor=actor,
                entry=entry,
                target_version=1,
                expected_version=99,
                reason="Stale",
            )
        assert revert_conflict.value == VersionConflictError(99, 3, reverted.id)

        with pytest.raises(ValueError) as missing_target:
            revert_entry(
                session,
                actor=actor,
                entry=entry,
                target_version=999,
                expected_version=3,
                reason="Missing",
            )
        assert missing_target.value.args == ("Target version does not exist",)

        assert version_diff(initial, edited) == [
            {
                "operation": "replace",
                "before": "Baseline line.\nRemove this line.",
                "after": "Baseline revised.\nAdded line.",
            }
        ]


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Routine neutral context.", None),
        (
            "Allergy documented.",
            (
                "critical",
                ["allergy"],
                "Allergy safety signal",
                "Allergy or severe reaction language requires prominent review",
            ),
        ),
        (
            "Chest pain reported.",
            (
                "critical",
                ["critical_result"],
                "Critical symptom signal",
                "Potentially urgent symptom language requires clinician review",
            ),
        ),
        (
            "Medication increased from 10 mg.",
            (
                "high",
                ["dose_change", "medication"],
                "Medication detail to reconcile",
                "Medication or dose information is a known high-risk scribe error class",
            ),
        ),
        (
            "New symptom is worsening.",
            (
                "high",
                ["symptom_change"],
                "Symptom change",
                "A new or worsening symptom may change the care plan",
            ),
        ),
        (
            "Lab follow-up pending.",
            (
                "medium",
                ["follow_up"],
                "Open follow-up",
                "An unresolved follow-up may require ownership or action",
            ),
        ),
        (
            "Assessment history reviewed.",
            (
                "low",
                ["clinical_context"],
                "Context to review",
                "Relevant longitudinal context",
            ),
        ),
        (
            "Suicidal concern with a medication dose and lab pending.",
            (
                "critical",
                ["critical_result", "follow_up", "medication"],
                "Critical symptom signal",
                "Potentially urgent symptom language requires clinician review",
            ),
        ),
    ],
)
def test_sentence_classifier_contract_is_exact(sentence, expected):
    assert _classify_sentence(sentence) == expected


@pytest.mark.parametrize(
    ("term", "expected_tag"),
    [
        ("anaphylaxis", "allergy"),
        ("facial swelling", "allergy"),
        ("shortness of breath", "critical_result"),
        ("lisinopril", "medication"),
        ("metformin", "medication"),
        ("dizziness", "symptom_change"),
        ("fainted", "symptom_change"),
        ("follow up", "follow_up"),
        ("await result", "follow_up"),
        ("diagnosis", "clinical_context"),
    ],
)
def test_sentence_classifier_synonym_contract(term: str, expected_tag: str):
    classified = _classify_sentence(f"Synthetic patient reports {term}.")
    assert classified is not None
    assert expected_tag in classified[1]


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        (
            "Dose recorded.",
            (
                "high",
                ["medication"],
                "Medication detail to reconcile",
                "Medication or dose information is a known high-risk scribe error class",
            ),
        ),
        (
            "Twenty mg recorded.",
            (
                "high",
                ["medication"],
                "Medication detail to reconcile",
                "Medication or dose information is a known high-risk scribe error class",
            ),
        ),
        *[
            (
                f"Medication {term} yesterday.",
                (
                    "high",
                    ["dose_change", "medication"],
                    "Medication detail to reconcile",
                    "Medication or dose information is a known high-risk scribe error class",
                ),
            )
            for term in ("changed", "increase", "decrease", "from baseline")
        ],
        *[
            (
                f"Patient reports {term}.",
                (
                    "high",
                    ["symptom_change"],
                    "Symptom change",
                    "A new or worsening symptom may change the care plan",
                ),
            )
            for term in ("worsening", "dizziness", "fainting", "new symptom")
        ],
        *[
            (
                f"Patient has {term}.",
                (
                    "medium",
                    ["follow_up"],
                    "Open follow-up",
                    "An unresolved follow-up may require ownership or action",
                ),
            )
            for term in ("follow-up", "follow up", "a lab", "pending work", "await results")
        ],
        *[
            (
                f"Patient {term} reviewed.",
                (
                    "low",
                    ["clinical_context"],
                    "Context to review",
                    "Relevant longitudinal context",
                ),
            )
            for term in ("diagnosis", "assessment", "history")
        ],
    ],
)
def test_sentence_classifier_each_trigger_has_an_independent_exact_contract(sentence, expected):
    assert _classify_sentence(sentence) == expected


def test_base_score_and_target_policy_probability_have_exact_numeric_contracts():
    now = datetime(2026, 8, 26, tzinfo=UTC)
    assert base_score(
        risk_level="critical",
        tags=["medication"],
        created_at=now,
        now=now,
        unresolved_action=True,
        explicitly_pinned=True,
    ) == (
        14.25,
        {
            "risk": 8.0,
            "entity_safety": 1.5,
            "recency": 1.5,
            "unresolved_action": 2.0,
            "explicit_pin": 1.25,
        },
    )
    assert _target_probability({}) == pytest.approx(0.2689414213699951)
    assert _target_probability({"base_score": 2.0, "risk_level": "low"}) == pytest.approx(
        0.36354745971843366
    )
    assert _target_probability({"base_score": 2.0, "risk_level": "high"}) == pytest.approx(
        0.5597136492671929
    )
    assert _target_probability({"base_score": 2.0, "risk_level": "critical"}) == pytest.approx(
        0.5597136492671929
    )


def test_base_score_defaults_non_safety_and_decay_have_exact_contracts():
    now = datetime(2026, 8, 26, tzinfo=UTC)
    assert base_score(
        risk_level="low",
        tags=["clinical_context"],
        created_at=now,
        now=now,
    ) == (
        2.5,
        {
            "risk": 1.0,
            "entity_safety": 0.0,
            "recency": 1.5,
            "unresolved_action": 0.0,
            "explicit_pin": 0.0,
        },
    )
    assert base_score(
        risk_level="medium",
        tags=["allergy"],
        created_at=datetime(2026, 4, 28, tzinfo=UTC),
        now=now,
    ) == (
        4.5518,
        {
            "risk": 2.5,
            "entity_safety": 1.5,
            "recency": 0.5518,
            "unresolved_action": 0.0,
            "explicit_pin": 0.0,
        },
    )


def test_adaptive_posterior_defaults_pooling_deduplication_and_update_are_exact(
    app, identities, monkeypatch
):
    updated_at = datetime(2026, 8, 26, 13, 45, tzinfo=UTC)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, timezone=None):
            assert timezone is UTC
            return updated_at

    monkeypatch.setattr(importance_module, "datetime", FixedDateTime)
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        assert actor is not None
        feature = "exact-contract-feature"
        assert (
            adaptive_score(
                session,
                clinic_id=actor.clinic_id,
                actor_role=actor.role,
                features=[feature, feature],
            )
            == 0.0
        )
        assert (
            session.scalars(
                select(FeaturePosterior).where(FeaturePosterior.feature == feature)
            ).all()
            == []
        )

        role_item = _posterior(
            session,
            clinic_id=actor.clinic_id,
            actor_role=actor.role,
            feature=feature,
            create=True,
        )
        global_item = _posterior(
            session,
            clinic_id=actor.clinic_id,
            actor_role="all",
            feature=feature,
            create=True,
        )
        assert role_item is not None and global_item is not None
        assert (
            role_item.clinic_id,
            role_item.actor_role,
            role_item.feature,
            role_item.alpha,
            role_item.beta,
            role_item.observations,
        ) == (actor.clinic_id, "clinician", feature, 2.0, 2.0, 0)
        role_item.alpha, role_item.beta = 8.0, 2.0
        global_item.alpha, global_item.beta = 3.0, 7.0
        assert (
            adaptive_score(
                session,
                clinic_id=actor.clinic_id,
                actor_role=actor.role,
                features=[feature, feature],
            )
            == 0.15
        )

        _update_posterior(role_item, 0.25)
        assert (
            role_item.alpha,
            role_item.beta,
            role_item.observations,
            role_item.updated_at,
        ) == (8.25, 2.75, 1, updated_at)


def test_shadow_policy_evaluation_contract_is_exact(app, identities, patient_id):
    assumptions = (
        "Consistency between logged and evaluated ranking interactions",
        "No unmeasured confounding conditional on the logged context",
        "Positive behavior propensity wherever the shadow policy assigns probability",
        "Correct behavior propensities or adequate outcome-model approximation",
    )
    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        highlight = session.scalar(select(Highlight).where(Highlight.patient_id == patient_id))
        assert clinician is not None and highlight is not None
        assert evaluate_shadow_policy(session, clinician.clinic_id) == PolicyEvaluation(
            estimand=(
                "Expected accepted/relevant highlight feedback under the shadow display policy"
            ),
            observations=0,
            effective_sample_size=0.0,
            behavior_value=None,
            doubly_robust_value=None,
            standard_error=None,
            ci_95=None,
            overlap_warning=True,
            exposure_bias_warning=True,
            status="insufficient_data",
            assumptions=assumptions,
        )


def test_audit_verification_orders_by_sequence_and_count_is_exact(app):
    with app.state.database.session() as session:
        clinic = Clinic(id="clinic-out-of-order-audit", name="Out-of-order audit fixture")
        session.add(clinic)
        session.flush()
        first = append_audit(
            session,
            clinic_id=clinic.id,
            actor_id=None,
            action="fixture.first",
            object_type="fixture",
            object_id="first",
            request_id="request-first",
            created_at=datetime(2026, 8, 26, 1, 0, tzinfo=UTC),
        )
        second = append_audit(
            session,
            clinic_id=clinic.id,
            actor_id=None,
            action="fixture.second",
            object_type="fixture",
            object_id="second",
            request_id="request-second",
            created_at=datetime(2026, 8, 26, 1, 1, tzinfo=UTC),
        )
        snapshots = [
            {column.name: getattr(event, column.name) for column in AuditEvent.__table__.columns}
            for event in (first, second)
        ]
        session.delete(first)
        session.delete(second)
        session.flush()
        session.add(AuditEvent(**snapshots[1]))
        session.flush()
        session.add(AuditEvent(**snapshots[0]))
        session.flush()

        assert audit_count(session, clinic.id) == 2

        class OrderRecordingSession:
            def scalars(self, statement):
                assert "ORDER BY audit_events.sequence" in str(statement)
                return session.scalars(statement)

        assert verify_audit_chain(OrderRecordingSession(), clinic.id) == AuditVerification(True, 2)


def test_posterior_create_flag_rejects_non_boolean_values(app, identities):
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        assert actor is not None
        with pytest.raises(TypeError) as error:
            _posterior(
                session,
                clinic_id=actor.clinic_id,
                actor_role=actor.role,
                feature="invalid-create-flag",
                create=None,  # type: ignore[arg-type]
            )
        assert error.value.args == ("create must be a boolean",)


def test_provenance_resolves_full_source_boundaries_and_exact_objects(app, identities, patient_id):
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        patient = session.get(Patient, patient_id)
        assert actor is not None and patient is not None
        entry = create_entry(
            session,
            actor=actor,
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Full provenance boundary",
            content="Allergy.",
            visibility="internal",
            trust_state="clinician_confirmed",
            source_uri="session://full-provenance-boundary",
        )
        version = session.get(EntryVersion, entry.current_version_id)
        assert version is not None
        span = create_span(
            session,
            entry=entry,
            version=version,
            start_offset=0,
            end_offset=len(version.content),
        )
        resolved = resolve_span(session, span)
        assert isinstance(resolved.span, ProvenanceSpan)
        assert resolved.span is span
        assert resolved.entry is entry
        assert resolved.version is version
        assert resolved.span.quote == version.content


def test_unversioned_entry_conflicts_return_an_empty_current_version_identifier(
    app, identities, patient_id
):
    with app.state.database.session() as session:
        actor = session.get(User, identities["clinician"])
        patient = session.get(Patient, patient_id)
        assert actor is not None and patient is not None
        entry = Entry(
            clinic_id=patient.clinic_id,
            patient_id=patient.id,
            author_id=actor.id,
            owner_role="clinician",
            entry_type="clinician_note",
            title="Unversioned defensive fixture",
            visibility="internal",
            trust_state="clinician_confirmed",
            current_version=0,
            current_version_id=None,
        )
        session.add(entry)
        session.flush()

        operations = (
            lambda: edit_entry(
                session,
                actor=actor,
                entry=entry,
                content="Blocked edit",
                expected_version=1,
                reason="Defensive conflict",
            ),
            lambda: revert_entry(
                session,
                actor=actor,
                entry=entry,
                target_version=1,
                expected_version=1,
                reason="Defensive conflict",
            ),
        )
        for operation in operations:
            with pytest.raises(VersionConflictError) as error:
                operation()
            assert error.value.expected_version == 1
            assert error.value.current_version == 0
            assert error.value.current_version_id == ""


def test_shadow_policy_two_observation_variance_and_unclipped_interval_are_exact(
    app, identities, patient_id
):
    context = {"base_score": 2.0, "risk_level": "low"}
    target = _target_probability(context)
    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        highlight = session.scalar(select(Highlight).where(Highlight.patient_id == patient_id))
        assert clinician is not None and highlight is not None

        def add(reward: float) -> None:
            session.add(
                ImportanceFeedback(
                    clinic_id=clinician.clinic_id,
                    highlight_id=highlight.id,
                    actor_id=clinician.id,
                    action="accept" if reward else "reject",
                    reward=reward,
                    policy_version="interval-contract",
                    display_propensity=target,
                    context=context,
                )
            )

        add(0.0)
        add(1.0)
        session.flush()
        two = evaluate_shadow_policy(session, clinician.clinic_id)
        assert (
            two.observations,
            two.behavior_value,
            two.doubly_robust_value,
            two.standard_error,
            two.ci_95,
        ) == (2, 0.5, 0.5, 0.5, (0.0, 1.0))

        for reward in (0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0):
            add(reward)
        session.flush()
        ten = evaluate_shadow_policy(session, clinician.clinic_id)
        assert (
            ten.observations,
            ten.effective_sample_size,
            ten.behavior_value,
            ten.doubly_robust_value,
            ten.standard_error,
            ten.ci_95,
            ten.overlap_warning,
        ) == (10, 10.0, 0.5, 0.5, 0.1667, (0.1733, 0.8267), False)


def test_shadow_policy_overlap_boundaries_are_exact(app, identities, patient_id):
    context = {"base_score": -100.0, "risk_level": "low"}
    with app.state.database.session() as session:
        clinician = session.get(User, identities["clinician"])
        highlight = session.scalar(select(Highlight).where(Highlight.patient_id == patient_id))
        assert clinician is not None and highlight is not None

        def replace_records(
            weights: list[float], record_context: dict | None = None
        ) -> PolicyEvaluation:
            selected_context = record_context or context
            selected_target = _target_probability(selected_context)
            for item in session.scalars(
                select(ImportanceFeedback).where(
                    ImportanceFeedback.clinic_id == clinician.clinic_id
                )
            ):
                session.delete(item)
            session.flush()
            session.add_all(
                [
                    ImportanceFeedback(
                        clinic_id=clinician.clinic_id,
                        highlight_id=highlight.id,
                        actor_id=clinician.id,
                        action="accept",
                        reward=0.5,
                        policy_version="overlap-contract",
                        display_propensity=selected_target / weight,
                        context=selected_context,
                    )
                    for weight in weights
                ]
            )
            session.flush()
            return evaluate_shadow_policy(session, clinician.clinic_id)

        ess_five = replace_records([1.0] * 5)
        assert (ess_five.effective_sample_size, ess_five.overlap_warning) == (5.0, False)

        sample_fraction = replace_records([1.0] * 6 + [0.05] * 34)
        assert (sample_fraction.observations, sample_fraction.effective_sample_size) == (
            40,
            9.744,
        )
        assert sample_fraction.overlap_warning is True

        moderate_context = {"base_score": 2.0, "risk_level": "low"}
        weight_ten = replace_records([10.0] * 6, moderate_context)
        assert (weight_ten.effective_sample_size, weight_ten.overlap_warning) == (6.0, False)

        weight_above_ten = replace_records([10.5] * 6, moderate_context)
        assert (
            weight_above_ten.effective_sample_size,
            weight_above_ten.overlap_warning,
        ) == (6.0, True)
        for item in session.scalars(
            select(ImportanceFeedback).where(ImportanceFeedback.clinic_id == clinician.clinic_id)
        ):
            session.delete(item)
        session.flush()
        assumptions = (
            "Consistency between logged and evaluated ranking interactions",
            "No unmeasured confounding conditional on the logged context",
            "Positive behavior propensity wherever the shadow policy assigns probability",
            "Correct behavior propensities or adequate outcome-model approximation",
        )
        record = ImportanceFeedback(
            clinic_id=clinician.clinic_id,
            highlight_id=highlight.id,
            actor_id=clinician.id,
            action="accept",
            reward=1.0,
            policy_version="contract-policy",
            display_propensity=0.5,
            context={"base_score": 2.0, "risk_level": "low"},
        )
        session.add(record)
        session.flush()
        assert evaluate_shadow_policy(session, clinician.clinic_id) == PolicyEvaluation(
            estimand=(
                "Expected accepted/relevant highlight feedback under the shadow display policy"
            ),
            observations=1,
            effective_sample_size=1.0,
            behavior_value=1.0,
            doubly_robust_value=1.0,
            standard_error=0.0,
            ci_95=(1.0, 1.0),
            overlap_warning=True,
            exposure_bias_warning=False,
            status="exploratory",
            assumptions=assumptions,
        )
        session.add_all(
            [
                ImportanceFeedback(
                    clinic_id=clinician.clinic_id,
                    highlight_id=highlight.id,
                    actor_id=clinician.id,
                    action="reject",
                    reward=0.0,
                    policy_version="contract-policy",
                    display_propensity=0.2,
                    context={"base_score": 8.0, "risk_level": "critical"},
                ),
                ImportanceFeedback(
                    clinic_id=clinician.clinic_id,
                    highlight_id=highlight.id,
                    actor_id=clinician.id,
                    action="accept",
                    reward=1.0,
                    policy_version="contract-policy",
                    display_propensity=0.01,
                    context={"base_score": 4.0, "risk_level": "high"},
                ),
            ]
        )
        session.flush()
        assert evaluate_shadow_policy(session, clinician.clinic_id) == PolicyEvaluation(
            estimand=(
                "Expected accepted/relevant highlight feedback under the shadow display policy"
            ),
            observations=3,
            effective_sample_size=1.147,
            behavior_value=0.6667,
            doubly_robust_value=7.2042,
            standard_error=7.8414,
            ci_95=(0.0, 1.0),
            overlap_warning=True,
            exposure_bias_warning=False,
            status="exploratory",
            assumptions=assumptions,
        )
