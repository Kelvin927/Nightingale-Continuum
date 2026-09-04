"""Seed one deterministic, fictional care journey for the local demonstration."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .care import create_entry, current_version
from .configuration import ClinicConfiguration, install_seed_configuration
from .importance import build_glance_projection, generate_highlights_for_entry
from .models import (
    CareTask,
    Clinic,
    Comment,
    CommentThread,
    Conflict,
    GlanceProjection,
    Patient,
    PatientContact,
    User,
)

PRIMARY_CLINIC_ID = "clinic-northstar"
OTHER_CLINIC_ID = "clinic-riverside"
PRIMARY_PATIENT_ID = "patient-maya-chen"
OTHER_PATIENT_ID = "patient-alex-rivera"
PRIMARY_CONTACT_ID = "contact-maya-whatsapp"

DEMO_USERS = {
    "clinician": "user-clinician-lina",
    "staff": "user-staff-jon",
    "patient": "user-patient-maya",
    "admin": "user-admin-rose",
    "system": "user-system-northstar",
    "other_clinician": "user-other-clinician",
}


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _ensure_demo_contact(session: Session) -> None:
    if session.get(PatientContact, PRIMARY_CONTACT_ID) is not None:
        return
    if session.get(Patient, PRIMARY_PATIENT_ID) is None:
        return
    session.add(
        PatientContact(
            id=PRIMARY_CONTACT_ID,
            clinic_id=PRIMARY_CLINIC_ID,
            patient_id=PRIMARY_PATIENT_ID,
            channel="whatsapp",
            routing_reference="vault://synthetic/contact-maya-whatsapp",
            masked_destination="WhatsApp ending 4567",
            consent_status="granted",
            preferred=True,
            active=True,
            verified_at=_dt("2026-02-06T08:30:00"),
            created_at=_dt("2026-02-06T08:30:00"),
        )
    )


def _ensure_demo_configurations(session: Session) -> None:
    """Install two deliberately different, schema-valid clinic configurations."""

    if session.get(Clinic, PRIMARY_CLINIC_ID) is not None:
        install_seed_configuration(
            session,
            clinic_id=PRIMARY_CLINIC_ID,
            configuration=ClinicConfiguration(
                clinic_display_name="Northstar Family Medicine",
                timezone="Asia/Singapore",
                enabled_languages=["en-SG", "zh-SG"],
                delivery_channels=["whatsapp", "sms"],
                features={
                    "streaming_capture": True,
                    "multilingual_review": True,
                    "outbound_delivery": True,
                    "adaptive_ranking_shadow_only": True,
                },
                safety={
                    "critical_risk_floor": 8.0,
                    "provider_timeout_ms": 2_000,
                    "delivery_receipt_sla_minutes": 15,
                    "require_dose_attestation": True,
                },
            ),
            created_at=_dt("2026-02-06T08:00:00"),
        )
    if session.get(Clinic, OTHER_CLINIC_ID) is not None:
        install_seed_configuration(
            session,
            clinic_id=OTHER_CLINIC_ID,
            configuration=ClinicConfiguration(
                clinic_display_name="Riverside Community Clinic",
                timezone="America/Los_Angeles",
                enabled_languages=["en-US", "es-US"],
                delivery_channels=["sms", "voice"],
                features={
                    "streaming_capture": True,
                    "multilingual_review": True,
                    "outbound_delivery": True,
                    "adaptive_ranking_shadow_only": True,
                },
                safety={
                    "critical_risk_floor": 9.0,
                    "provider_timeout_ms": 2_500,
                    "delivery_receipt_sla_minutes": 10,
                    "require_dose_attestation": True,
                },
            ),
            created_at=_dt("2026-02-06T08:00:00"),
        )


def seed_database(session: Session) -> None:
    if session.scalar(select(Clinic.id).limit(1)) is not None:
        _ensure_demo_contact(session)
        _ensure_demo_configurations(session)
        session.commit()
        return

    northstar = Clinic(id=PRIMARY_CLINIC_ID, name="Northstar Family Medicine")
    riverside = Clinic(id=OTHER_CLINIC_ID, name="Riverside Community Clinic")
    session.add_all([northstar, riverside])

    maya = Patient(
        id=PRIMARY_PATIENT_ID,
        clinic_id=northstar.id,
        display_name="Maya Chen",
        initials="MC",
        synthetic_record_number="SYN-2048",
        date_of_birth="1988-07-12",
        pronouns="she/her",
        synthetic=True,
    )
    alex = Patient(
        id=OTHER_PATIENT_ID,
        clinic_id=riverside.id,
        display_name="Alex Rivera",
        initials="AR",
        synthetic_record_number="SYN-9901",
        date_of_birth="1976-11-03",
        pronouns="they/them",
        synthetic=True,
    )
    session.add_all([maya, alex])
    session.flush()
    _ensure_demo_contact(session)
    _ensure_demo_configurations(session)

    users = {
        "clinician": User(
            id=DEMO_USERS["clinician"],
            clinic_id=northstar.id,
            display_name="Dr Lina Patel",
            role="clinician",
        ),
        "staff": User(
            id=DEMO_USERS["staff"],
            clinic_id=northstar.id,
            display_name="Jon Bell",
            role="staff",
        ),
        "patient": User(
            id=DEMO_USERS["patient"],
            clinic_id=northstar.id,
            display_name="Maya Chen",
            role="patient",
            patient_id=maya.id,
        ),
        "admin": User(
            id=DEMO_USERS["admin"],
            clinic_id=northstar.id,
            display_name="Rose Tan",
            role="admin",
        ),
        "system": User(
            id=DEMO_USERS["system"],
            clinic_id=northstar.id,
            display_name="Nightingale AI",
            role="system",
        ),
        "other_clinician": User(
            id=DEMO_USERS["other_clinician"],
            clinic_id=riverside.id,
            display_name="Dr Morgan Lee",
            role="clinician",
        ),
    }
    session.add_all(list(users.values()))
    session.flush()

    old_history = create_entry(
        session,
        actor=users["clinician"],
        clinic_id=northstar.id,
        patient_id=maya.id,
        owner_role="clinician",
        entry_type="clinician_note",
        title="Baseline hypertension review",
        content=(
            "Blood pressure was above the home target. "
            "Medication remained lisinopril 10 mg daily. Follow-up was planned in three months."
        ),
        visibility="internal",
        trust_state="clinician_confirmed",
        created_at=_dt("2025-04-15T09:20:00"),
    )
    ai_session = create_entry(
        session,
        actor=users["system"],
        clinic_id=northstar.id,
        patient_id=maya.id,
        owner_role="system",
        entry_type="ai_patient_session_summary",
        title="Pre-visit AI session",
        content=(
            "AI-GENERATED DRAFT - HUMAN REVIEW REQUIRED\n\n"
            "Patient reports dizziness since the lisinopril dose changed from 10 mg to 20 mg. "
            "She is awaiting a nurse follow-up and asks whether the new dose should continue."
        ),
        visibility="internal",
        trust_state="ai_proposed",
        source_uri="session://synthetic/ai-patient-2026-02-06",
        created_at=_dt("2026-02-06T08:41:00"),
    )
    staff_note = create_entry(
        session,
        actor=users["staff"],
        clinic_id=northstar.id,
        patient_id=maya.id,
        owner_role="staff",
        entry_type="staff_note",
        title="Follow-up coordination",
        content=(
            "Home blood pressure log received. Renal function lab order remains pending. "
            "Nurse follow-up is awaiting clinician guidance on timing."
        ),
        visibility="internal",
        trust_state="staff_verified",
        created_at=_dt("2026-02-06T09:05:00"),
    )
    clinician_plan = create_entry(
        session,
        actor=users["clinician"],
        clinic_id=northstar.id,
        patient_id=maya.id,
        owner_role="clinician",
        entry_type="clinician_note",
        title="Assessment and plan",
        content=(
            "Allergy: penicillin caused facial swelling in childhood. "
            "Dizziness may be temporally associated with the recent lisinopril dose increase; "
            "causality is not established. Continue home blood pressure monitoring. "
            "Obtain renal function lab before deciding on the medication dose."
        ),
        visibility="internal",
        trust_state="clinician_confirmed",
        created_at=_dt("2026-02-06T10:10:00"),
    )
    create_entry(
        session,
        actor=users["clinician"],
        clinic_id=northstar.id,
        patient_id=maya.id,
        owner_role="clinician",
        entry_type="patient_summary",
        title="Your visit summary",
        content=(
            "Please keep recording your blood pressure. "
            "The clinic will contact you after the lab result is reviewed. "
            "Seek urgent care if dizziness becomes severe, you faint, or you develop chest pain."
        ),
        visibility="patient",
        trust_state="clinician_confirmed",
        created_at=_dt("2026-02-06T10:18:00"),
    )

    create_entry(
        session,
        actor=users["other_clinician"],
        clinic_id=riverside.id,
        patient_id=alex.id,
        owner_role="clinician",
        entry_type="clinician_note",
        title="Other clinic record",
        content="Synthetic content belonging to a different clinic.",
        visibility="internal",
        trust_state="clinician_confirmed",
        created_at=_dt("2026-02-07T10:00:00"),
    )

    for entry in (old_history, ai_session, staff_note, clinician_plan):
        generate_highlights_for_entry(session, entry=entry)

    task = CareTask(
        clinic_id=northstar.id,
        patient_id=maya.id,
        source_entry_id=staff_note.id,
        title="Place renal function lab order",
        status="open",
        urgency="high",
        assigned_to=users["staff"].id,
        due_at=_dt("2026-02-07T12:00:00"),
        created_by=users["staff"].id,
        created_at=_dt("2026-02-06T09:08:00"),
    )
    session.add(task)

    thread = CommentThread(
        clinic_id=northstar.id,
        entry_id=staff_note.id,
        title="Confirm dose plan before patient callback",
        resolved=False,
        created_at=_dt("2026-02-06T09:12:00"),
    )
    session.add(thread)
    session.flush()
    session.add(
        Comment(
            thread_id=thread.id,
            author_id=users["staff"].id,
            body="@Dr Lina Patel Could you confirm whether we should wait for the lab result?",
            mentions=[users["clinician"].id],
            assigned_to=users["clinician"].id,
            created_at=_dt("2026-02-06T09:13:00"),
        )
    )

    session.add(
        Conflict(
            clinic_id=northstar.id,
            patient_id=maya.id,
            left_version_id=current_version(session, ai_session).id,
            right_version_id=current_version(session, clinician_plan).id,
            conflict_type="medication_plan_uncertainty",
            summary=(
                "AI session asks whether to continue 20 mg; clinician plan defers the decision "
                "pending labs."
            ),
            status="open",
            created_at=_dt("2026-02-06T10:12:00"),
        )
    )

    projection = GlanceProjection(
        patient_id=maya.id,
        clinic_id=northstar.id,
        payload=build_glance_projection(session, maya.id),
        source_revision=1,
    )
    session.add(projection)
    session.commit()
