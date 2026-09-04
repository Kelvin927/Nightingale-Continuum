"""Define the longitudinal record, provenance, learning, and audit schema."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .constants import POLICY_VERSION


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_clinic_role", "clinic_id", "role"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    patient_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("clinic_id", "synthetic_record_number", name="uq_patient_record_clinic"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    initials: Mapped[str] = mapped_column(String(12), nullable=False)
    synthetic_record_number: Mapped[str] = mapped_column(String(32), nullable=False)
    date_of_birth: Mapped[str] = mapped_column(String(10), nullable=False)
    pronouns: Mapped[str] = mapped_column(String(40), nullable=False, default="they/them")
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (
        Index("ix_entries_patient_time", "patient_id", "created_at"),
        Index("ix_entries_clinic_patient", "clinic_id", "patient_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    owner_role: Mapped[str] = mapped_column(String(24), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    visibility: Mapped[str] = mapped_column(String(24), nullable=False, default="internal")
    trust_state: Mapped[str] = mapped_column(String(32), nullable=False, default="human_authored")
    source_uri: Mapped[str | None] = mapped_column(String(300), nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retention_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="hot")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EntryVersion(Base):
    __tablename__ = "entry_versions"
    __table_args__ = (
        UniqueConstraint("entry_id", "version", name="uq_entry_version"),
        Index("ix_entry_versions_entry", "entry_id", "version"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    change_reason: Mapped[str] = mapped_column(String(240), nullable=False)
    reverted_from_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CommentThread(Base):
    __tablename__ = "comment_threads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("comment_threads.id"), nullable=False, index=True
    )
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    mentions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CareTask(Base):
    __tablename__ = "care_tasks"
    __table_args__ = (Index("ix_tasks_patient_status", "patient_id", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    source_entry_id: Mapped[str | None] = mapped_column(ForeignKey("entries.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    urgency: Mapped[str] = mapped_column(String(24), nullable=False, default="routine")
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProvenanceSpan(Base):
    __tablename__ = "provenance_spans"
    __table_args__ = (Index("ix_provenance_patient", "patient_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    source_entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), nullable=False)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("entry_versions.id"), nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Highlight(Base):
    __tablename__ = "highlights"
    __table_args__ = (
        Index("ix_highlights_patient_status", "patient_id", "status"),
        Index("ix_highlights_clinic_patient", "clinic_id", "patient_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    provenance_span_id: Mapped[str] = mapped_column(
        ForeignKey("provenance_spans.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_reason: Mapped[str] = mapped_column(String(280), nullable=False)
    entity_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_support: Mapped[float] = mapped_column("confidence", Float, nullable=False)
    trust_state: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="suggested")
    base_score: Mapped[float] = mapped_column(Float, nullable=False)
    adaptive_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rank_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_factors: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False, default=POLICY_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ImportanceFeedback(Base):
    __tablename__ = "importance_feedback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    highlight_id: Mapped[str] = mapped_column(ForeignKey("highlights.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    reward: Mapped[float] = mapped_column(Float, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    display_propensity: Mapped[float] = mapped_column(Float, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FeaturePosterior(Base):
    __tablename__ = "feature_posteriors"
    __table_args__ = (
        UniqueConstraint("clinic_id", "actor_role", "feature", name="uq_feature_posterior"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(24), nullable=False)
    feature: Mapped[str] = mapped_column(String(80), nullable=False)
    alpha: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    beta: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Conflict(Base):
    __tablename__ = "conflicts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    left_version_id: Mapped[str] = mapped_column(ForeignKey("entry_versions.id"), nullable=False)
    right_version_id: Mapped[str] = mapped_column(ForeignKey("entry_versions.id"), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(280), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    disposition: Mapped[str | None] = mapped_column(String(280), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_clinic_sequence", "clinic_id", "sequence"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    object_type: Mapped[str] = mapped_column(String(80), nullable=False)
    object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    object_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RetentionManifest(Base):
    __tablename__ = "retention_manifests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), nullable=False, index=True)
    from_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    to_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(280), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dropped_derivatives: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GlanceProjection(Base):
    __tablename__ = "glance_projections"

    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), primary_key=True)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PatientContact(Base):
    __tablename__ = "patient_contacts"
    __table_args__ = (
        UniqueConstraint(
            "patient_id",
            "channel",
            "routing_reference",
            name="uq_patient_contact_route",
        ),
        Index("ix_patient_contacts_clinic_patient", "clinic_id", "patient_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    routing_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    masked_destination: Mapped[str] = mapped_column(String(80), nullable=False)
    consent_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    preferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PatientAccessClaim(Base):
    __tablename__ = "patient_access_claims"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_patient_access_claim_token"),
        Index("ix_patient_access_claim_contact_created", "contact_id", "created_at"),
        Index("ix_patient_access_claim_clinic_patient", "clinic_id", "patient_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("patient_contacts.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="issued")
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    issued_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PatientAccessGrant(Base):
    __tablename__ = "patient_access_grants"
    __table_args__ = (
        UniqueConstraint("session_token_hash", name="uq_patient_access_grant_token"),
        Index("ix_patient_access_grant_clinic_patient", "clinic_id", "patient_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    access_claim_id: Mapped[str] = mapped_column(
        ForeignKey("patient_access_claims.id"), nullable=False
    )
    session_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    device_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OutboundDelivery(Base):
    __tablename__ = "outbound_deliveries"
    __table_args__ = (
        UniqueConstraint("clinic_id", "idempotency_key", name="uq_delivery_idempotency"),
        Index("ix_deliveries_patient_created", "patient_id", "created_at"),
        Index("ix_deliveries_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    source_entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), nullable=False)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("entry_versions.id"), nullable=False)
    contact_id: Mapped[str] = mapped_column(ForeignKey("patient_contacts.id"), nullable=False)
    correction_for_id: Mapped[str | None] = mapped_column(
        ForeignKey("outbound_deliveries.id"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    masked_destination: Mapped[str] = mapped_column(String(80), nullable=False)
    content_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    approval_evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ClinicConfigVersion(Base):
    __tablename__ = "clinic_config_versions"
    __table_args__ = (
        UniqueConstraint("clinic_id", "revision", name="uq_clinic_config_revision"),
        Index("ix_clinic_config_status", "clinic_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(24), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    activated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CaptureSession(Base):
    __tablename__ = "capture_sessions"
    __table_args__ = (
        Index("ix_capture_sessions_patient_status", "patient_id", "status"),
        Index("ix_capture_sessions_clinic_started", "clinic_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    initiated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    interaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="streaming")
    latest_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stream_contract_version: Mapped[str] = mapped_column(String(24), nullable=False)
    capability_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    finalized_entry_id: Mapped[str | None] = mapped_column(ForeignKey("entries.id"), nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        UniqueConstraint("capture_session_id", "sequence", name="uq_segment_sequence"),
        UniqueConstraint("capture_session_id", "chunk_id", name="uq_segment_chunk"),
        Index("ix_transcript_segments_capture_sequence", "capture_session_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    capture_session_id: Mapped[str] = mapped_column(
        ForeignKey("capture_sessions.id"), nullable=False
    )
    correction_of_segment_id: Mapped[str | None] = mapped_column(
        ForeignKey("transcript_segments.id"), nullable=True
    )
    chunk_id: Mapped[str] = mapped_column(String(80), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker_label: Mapped[str] = mapped_column(String(24), nullable=False)
    verbatim_text: Mapped[str] = mapped_column(Text, nullable=False)
    language_spans: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    asr_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    audio_quality: Mapped[float] = mapped_column(Float, nullable=False)
    processing_state: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="provisional")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SafetySignal(Base):
    __tablename__ = "safety_signals"
    __table_args__ = (
        UniqueConstraint(
            "source_segment_id",
            "signal_type",
            "source_start_offset",
            "source_end_offset",
            name="uq_segment_safety_signal",
        ),
        Index("ix_safety_signals_patient_state", "patient_id", "review_state"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    capture_session_id: Mapped[str] = mapped_column(
        ForeignKey("capture_sessions.id"), nullable=False
    )
    source_segment_id: Mapped[str] = mapped_column(
        ForeignKey("transcript_segments.id"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(40), nullable=False)
    normalized_label: Mapped[str] = mapped_column(String(120), nullable=False)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    source_end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_quality: Mapped[str] = mapped_column(String(24), nullable=False)
    review_state: Mapped[str] = mapped_column(String(32), nullable=False)
    review_rationale: Mapped[str | None] = mapped_column(String(280), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
