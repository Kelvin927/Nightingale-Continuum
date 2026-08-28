"""Expose the role-scoped FastAPI surface and transactional care workflows."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import append_audit, verify_audit_chain
from .care import (
    VersionConflictError,
    create_entry,
    current_version,
    edit_entry,
    revert_entry,
    version_diff,
)
from .conflicts import detect_structured_conflicts
from .constants import DETERMINISTIC_DISPLAY_PROPENSITY
from .database import Database, sqlite_version
from .delta import build_delta_lens
from .evaluation import evaluate_shadow_policy
from .importance import (
    build_glance_projection,
    generate_highlights_for_entry,
    record_feedback,
)
from .models import (
    AuditEvent,
    Comment,
    CommentThread,
    Conflict,
    Entry,
    EntryVersion,
    GlanceProjection,
    Highlight,
    Patient,
    ProvenanceSpan,
    User,
)
from .policy import (
    can_view_internal,
    conceal,
    forbidden,
    patient_can_read_entry,
    require_admin,
    require_create_entry,
    require_entry_edit,
    require_entry_read,
    require_internal_collaboration,
    require_patient,
    require_thread,
    resolve_actor,
)
from .provenance import InvalidProvenanceError, resolve_span
from .retention import apply_retention_policy
from .review import build_evidence_review
from .schemas import (
    CreateCommentRequest,
    CreateEntryRequest,
    CreateThreadRequest,
    EditEntryRequest,
    EvidenceReviewRequest,
    FeedbackRequest,
    ResolveThreadRequest,
    RetentionRunRequest,
    RevertEntryRequest,
    ScribeIngestRequest,
)
from .scribe import (
    LocalDeterministicScribe,
    RedactionFidelityError,
    ingest_scribe,
    receipt_dict,
)
from .seed import DEMO_USERS, seed_database

API_PREFIX = "/api/v1"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def get_session(request: Request) -> Iterator[Session]:
    database: Database = request.app.state.database
    with database.session() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_actor(
    session: SessionDep,
    x_demo_user: Annotated[str | None, Header(alias="X-Demo-User")] = None,
) -> User:
    return resolve_actor(session, x_demo_user)


ActorDep = Annotated[User, Depends(get_actor)]


def _author(session: Session, author_id: str | None) -> dict | None:
    if author_id is None:
        return None
    user = session.get(User, author_id)
    if user is None:
        return {"id": author_id, "display_name": "Unknown", "role": "unknown"}
    return {"id": user.id, "display_name": user.display_name, "role": user.role}


def _serialize_version(version: EntryVersion, *, include_content: bool = True) -> dict:
    payload = {
        "id": version.id,
        "version": version.version,
        "content_hash": version.content_hash,
        "created_by": version.created_by,
        "change_reason": version.change_reason,
        "reverted_from_version_id": version.reverted_from_version_id,
        "created_at": _iso(version.created_at),
    }
    if include_content:
        payload["content"] = version.content
    return payload


def _serialize_entry(session: Session, entry: Entry, actor: User) -> dict:
    version = current_version(session, entry)
    payload = {
        "id": entry.id,
        "patient_id": entry.patient_id,
        "entry_type": entry.entry_type,
        "title": entry.title,
        "owner_role": entry.owner_role,
        "author": _author(session, entry.author_id),
        "visibility": entry.visibility,
        "trust_state": entry.trust_state,
        "source_uri": entry.source_uri,
        "current_version": entry.current_version,
        "retention_tier": entry.retention_tier,
        "created_at": _iso(entry.created_at),
        "updated_at": _iso(entry.updated_at),
        "version": _serialize_version(version),
    }
    if can_view_internal(actor):
        threads = list(
            session.scalars(
                select(CommentThread)
                .where(CommentThread.entry_id == entry.id)
                .order_by(CommentThread.created_at)
            )
        )
        payload["comment_threads"] = [
            {
                "id": thread.id,
                "title": thread.title,
                "resolved": thread.resolved,
                "resolved_by": thread.resolved_by,
                "comments": [
                    {
                        "id": comment.id,
                        "body": comment.body,
                        "author": _author(session, comment.author_id),
                        "mentions": comment.mentions,
                        "assigned_to": comment.assigned_to,
                        "created_at": _iso(comment.created_at),
                    }
                    for comment in session.scalars(
                        select(Comment)
                        .where(Comment.thread_id == thread.id)
                        .order_by(Comment.created_at)
                    )
                ],
            }
            for thread in threads
        ]
    return payload


def _refresh_projection(session: Session, patient: Patient) -> GlanceProjection:
    projection = session.get(GlanceProjection, patient.id)
    payload = build_glance_projection(session, patient.id)
    if projection is None:
        projection = GlanceProjection(
            patient_id=patient.id,
            clinic_id=patient.clinic_id,
            payload=payload,
            source_revision=1,
        )
        session.add(projection)
    else:
        projection.payload = payload
        projection.source_revision += 1
        projection.updated_at = datetime.now(UTC)
    session.flush()
    return projection


def _validate_collaborators(session: Session, actor: User, user_ids: list[str]) -> None:
    for user_id in set(user_ids):
        user = session.scalar(
            select(User).where(User.id == user_id, User.clinic_id == actor.clinic_id)
        )
        if user is None or user.role not in {"staff", "clinician", "admin"}:
            raise forbidden("invalid_collaborator")


def _conflict_response(exc: VersionConflictError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "version_conflict",
            "message": "The section changed after it was loaded.",
            "expected_version": exc.expected_version,
            "current_version": exc.current_version,
            "current_version_id": exc.current_version_id,
            "resolution": "Reload the current version, compare, and resubmit intentionally.",
        },
    )


def create_app(
    *,
    database_url: str | None = None,
    seed_data: bool = True,
) -> FastAPI:
    app = FastAPI(
        title="Nightingale Continuum API",
        version="0.1.0",
        description="Evidence-bound longitudinal care-note prototype using synthetic data only.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "X-Demo-User", "X-Request-ID"],
    )

    resolved_url = database_url or os.getenv(
        "NIGHTINGALE_DATABASE_URL", "sqlite:///./nightingale.db"
    )
    database = Database(resolved_url)
    database.create_all()
    if seed_data:
        with database.session() as session:
            seed_database(session)
    app.state.database = database
    app.state.scribe_provider = LocalDeterministicScribe()

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), payment=()"
        return response

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "service": "nightingale-continuum-api",
            "synthetic_data_only": True,
            "database": "sqlite",
            "sqlite_version": sqlite_version(database.engine),
        }

    @app.get(f"{API_PREFIX}/demo/identities")
    def demo_identities(session: SessionDep) -> dict:
        users = list(
            session.scalars(
                select(User)
                .where(
                    User.id.in_(
                        [DEMO_USERS[key] for key in ("clinician", "staff", "patient", "admin")]
                    )
                )
                .order_by(User.role)
            )
        )
        return {
            "warning": "Demo authentication and synthetic records only.",
            "identities": [
                {"id": user.id, "display_name": user.display_name, "role": user.role}
                for user in users
            ],
        }

    @app.get(f"{API_PREFIX}/me")
    def me(actor: ActorDep) -> dict:
        return {
            "id": actor.id,
            "display_name": actor.display_name,
            "role": actor.role,
            "clinic_id": actor.clinic_id,
            "patient_id": actor.patient_id,
            "authentication_mode": "demo_header",
        }

    @app.get(f"{API_PREFIX}/patients")
    def list_patients(session: SessionDep, actor: ActorDep) -> dict:
        query = select(Patient).where(Patient.clinic_id == actor.clinic_id)
        if actor.role == "patient":
            query = query.where(Patient.id == actor.patient_id)
        patients = list(session.scalars(query.order_by(Patient.display_name)))
        return {
            "patients": [
                {
                    "id": patient.id,
                    "display_name": patient.display_name,
                    "initials": patient.initials,
                    "synthetic_record_number": patient.synthetic_record_number,
                    "date_of_birth": patient.date_of_birth,
                    "pronouns": patient.pronouns,
                    "synthetic": patient.synthetic,
                }
                for patient in patients
            ]
        }

    @app.get(f"{API_PREFIX}/patients/{{patient_id}}/workspace")
    def patient_workspace(patient_id: str, session: SessionDep, actor: ActorDep) -> dict:
        patient = require_patient(session, actor, patient_id)
        entries = list(
            session.scalars(
                select(Entry)
                .where(Entry.patient_id == patient.id, Entry.clinic_id == actor.clinic_id)
                .order_by(Entry.created_at.desc())
            )
        )
        if actor.role == "patient":
            entries = [entry for entry in entries if patient_can_read_entry(entry)]
        conflicts = []
        if can_view_internal(actor):
            conflicts = [
                {
                    "id": item.id,
                    "conflict_type": item.conflict_type,
                    "summary": item.summary,
                    "status": item.status,
                    "disposition": item.disposition,
                }
                for item in session.scalars(
                    select(Conflict)
                    .where(Conflict.patient_id == patient.id)
                    .order_by(Conflict.created_at.desc())
                )
            ]
        return {
            "patient": {
                "id": patient.id,
                "display_name": patient.display_name,
                "initials": patient.initials,
                "synthetic_record_number": patient.synthetic_record_number,
                "date_of_birth": patient.date_of_birth,
                "pronouns": patient.pronouns,
                "synthetic": patient.synthetic,
            },
            "viewer": {"id": actor.id, "role": actor.role},
            "entries": [_serialize_entry(session, entry, actor) for entry in entries],
            "conflicts": conflicts,
        }

    @app.get(f"{API_PREFIX}/patients/{{patient_id}}/glance")
    def patient_glance(patient_id: str, session: SessionDep, actor: ActorDep) -> dict:
        patient = require_patient(session, actor, patient_id)
        if actor.role == "patient":
            entries = list(
                session.scalars(
                    select(Entry)
                    .where(
                        Entry.patient_id == patient.id,
                        Entry.clinic_id == actor.clinic_id,
                        Entry.visibility == "patient",
                    )
                    .order_by(Entry.created_at.desc())
                )
            )
            safe_entries = [entry for entry in entries if patient_can_read_entry(entry)]
            return {
                "patient_mode": True,
                "groups": {
                    "act_now": [],
                    "watch": [
                        {
                            "id": entry.id,
                            "title": entry.title,
                            "trust_state": entry.trust_state,
                            "entry_type": entry.entry_type,
                            "content": current_version(session, entry).content,
                        }
                        for entry in safe_entries[:3]
                    ],
                    "awaiting": [],
                },
                "safety_rule": "Only clinician-approved patient-facing content is shown here.",
            }
        projection = session.get(GlanceProjection, patient.id)
        if projection is None:
            projection = _refresh_projection(session, patient)
            session.commit()
        return {
            **projection.payload,
            "patient_mode": False,
            "source_revision": projection.source_revision,
            "projection_updated_at": _iso(projection.updated_at),
        }

    @app.get(f"{API_PREFIX}/patients/{{patient_id}}/delta")
    def patient_delta(patient_id: str, session: SessionDep, actor: ActorDep) -> dict:
        require_internal_collaboration(actor)
        patient = require_patient(session, actor, patient_id)
        return build_delta_lens(session, patient.id)

    @app.post(f"{API_PREFIX}/patients/{{patient_id}}/entries", status_code=201)
    def add_entry(
        patient_id: str,
        payload: CreateEntryRequest,
        session: SessionDep,
        actor: ActorDep,
        x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
    ) -> dict:
        patient = require_patient(session, actor, patient_id)
        require_create_entry(actor, payload.entry_type, payload.visibility)
        entry = create_entry(
            session,
            actor=actor,
            clinic_id=actor.clinic_id,
            patient_id=patient.id,
            owner_role=actor.role,
            entry_type=payload.entry_type,
            title=payload.title,
            content=payload.content,
            visibility=payload.visibility,
            trust_state="human_authored" if actor.role != "clinician" else "clinician_confirmed",
            request_id=x_request_id,
        )
        generate_highlights_for_entry(session, entry=entry, actor_role=actor.role)
        detect_structured_conflicts(session, entry)
        if actor.role != "patient":
            _refresh_projection(session, patient)
        session.commit()
        return _serialize_entry(session, entry, actor)

    @app.patch(f"{API_PREFIX}/entries/{{entry_id}}")
    def update_entry(
        entry_id: str,
        payload: EditEntryRequest,
        session: SessionDep,
        actor: ActorDep,
        x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
    ) -> dict:
        entry = require_entry_edit(session, actor, entry_id)
        try:
            edit_entry(
                session,
                actor=actor,
                entry=entry,
                content=payload.content,
                expected_version=payload.expected_version,
                reason=payload.reason,
                request_id=x_request_id,
            )
        except VersionConflictError as exc:
            session.rollback()
            raise _conflict_response(exc) from exc
        generate_highlights_for_entry(session, entry=entry, actor_role=actor.role)
        detect_structured_conflicts(session, entry)
        patient = require_patient(session, actor, entry.patient_id)
        if actor.role != "patient":
            _refresh_projection(session, patient)
        session.commit()
        return _serialize_entry(session, entry, actor)

    @app.get(f"{API_PREFIX}/entries/{{entry_id}}/versions")
    def entry_versions(entry_id: str, session: SessionDep, actor: ActorDep) -> dict:
        entry = require_entry_read(session, actor, entry_id)
        versions = list(
            session.scalars(
                select(EntryVersion)
                .where(EntryVersion.entry_id == entry.id)
                .order_by(EntryVersion.version.desc())
            )
        )
        return {
            "entry_id": entry.id,
            "current_version": entry.current_version,
            "versions": [_serialize_version(item) for item in versions],
        }

    @app.get(f"{API_PREFIX}/entries/{{entry_id}}/diff")
    def entry_diff(
        entry_id: str,
        session: SessionDep,
        actor: ActorDep,
        from_version: Annotated[int, Query(ge=1)],
        to_version: Annotated[int, Query(ge=1)],
    ) -> dict:
        entry = require_entry_read(session, actor, entry_id)
        versions = {
            item.version: item
            for item in session.scalars(
                select(EntryVersion).where(
                    EntryVersion.entry_id == entry.id,
                    EntryVersion.version.in_([from_version, to_version]),
                )
            )
        }
        if set(versions) != {from_version, to_version}:
            raise conceal()
        return {
            "entry_id": entry.id,
            "from_version": from_version,
            "to_version": to_version,
            "changes": version_diff(versions[from_version], versions[to_version]),
        }

    @app.post(f"{API_PREFIX}/entries/{{entry_id}}/revert")
    def revert(
        entry_id: str,
        payload: RevertEntryRequest,
        session: SessionDep,
        actor: ActorDep,
        x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
    ) -> dict:
        entry = require_entry_edit(session, actor, entry_id)
        try:
            revert_entry(
                session,
                actor=actor,
                entry=entry,
                target_version=payload.target_version,
                expected_version=payload.expected_version,
                reason=payload.reason,
                request_id=x_request_id,
            )
        except VersionConflictError as exc:
            session.rollback()
            raise _conflict_response(exc) from exc
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=404, detail="Target version not found") from exc
        generate_highlights_for_entry(session, entry=entry, actor_role=actor.role)
        detect_structured_conflicts(session, entry)
        patient = require_patient(session, actor, entry.patient_id)
        if actor.role != "patient":
            _refresh_projection(session, patient)
        session.commit()
        return _serialize_entry(session, entry, actor)

    @app.post(f"{API_PREFIX}/entries/{{entry_id}}/comments", status_code=201)
    def create_thread(
        entry_id: str,
        payload: CreateThreadRequest,
        session: SessionDep,
        actor: ActorDep,
    ) -> dict:
        require_internal_collaboration(actor)
        entry = require_entry_read(session, actor, entry_id)
        collaborators = payload.mentions + ([payload.assigned_to] if payload.assigned_to else [])
        _validate_collaborators(session, actor, collaborators)
        thread = CommentThread(
            clinic_id=actor.clinic_id,
            entry_id=entry.id,
            title=payload.title,
        )
        session.add(thread)
        session.flush()
        comment = Comment(
            thread_id=thread.id,
            author_id=actor.id,
            body=payload.body,
            mentions=payload.mentions,
            assigned_to=payload.assigned_to,
        )
        session.add(comment)
        session.flush()
        append_audit(
            session,
            clinic_id=actor.clinic_id,
            actor_id=actor.id,
            action="comment_thread.created",
            object_type="comment_thread",
            object_id=thread.id,
            metadata={
                "entry_id": entry.id,
                "mention_count": len(payload.mentions),
                "assigned": bool(payload.assigned_to),
            },
        )
        patient = require_patient(session, actor, entry.patient_id)
        _refresh_projection(session, patient)
        session.commit()
        return {"id": thread.id, "comment_id": comment.id, "resolved": False}

    @app.post(f"{API_PREFIX}/comment-threads/{{thread_id}}/comments", status_code=201)
    def add_comment(
        thread_id: str,
        payload: CreateCommentRequest,
        session: SessionDep,
        actor: ActorDep,
    ) -> dict:
        thread = require_thread(session, actor, thread_id)
        collaborators = payload.mentions + ([payload.assigned_to] if payload.assigned_to else [])
        _validate_collaborators(session, actor, collaborators)
        comment = Comment(
            thread_id=thread.id,
            author_id=actor.id,
            body=payload.body,
            mentions=payload.mentions,
            assigned_to=payload.assigned_to,
        )
        session.add(comment)
        session.flush()
        append_audit(
            session,
            clinic_id=actor.clinic_id,
            actor_id=actor.id,
            action="comment.created",
            object_type="comment",
            object_id=comment.id,
            metadata={"thread_id": thread.id, "mention_count": len(payload.mentions)},
        )
        entry = require_entry_read(session, actor, thread.entry_id)
        patient = require_patient(session, actor, entry.patient_id)
        _refresh_projection(session, patient)
        session.commit()
        return {"id": comment.id, "thread_id": thread.id}

    @app.post(f"{API_PREFIX}/comment-threads/{{thread_id}}/resolve")
    def resolve_thread(
        thread_id: str,
        payload: ResolveThreadRequest,
        session: SessionDep,
        actor: ActorDep,
    ) -> dict:
        thread = require_thread(session, actor, thread_id)
        thread.resolved = payload.resolved
        thread.resolved_by = actor.id if payload.resolved else None
        append_audit(
            session,
            clinic_id=actor.clinic_id,
            actor_id=actor.id,
            action="comment_thread.resolved" if payload.resolved else "comment_thread.reopened",
            object_type="comment_thread",
            object_id=thread.id,
            metadata={"resolved": payload.resolved},
        )
        entry = require_entry_read(session, actor, thread.entry_id)
        patient = require_patient(session, actor, entry.patient_id)
        _refresh_projection(session, patient)
        session.commit()
        return {"id": thread.id, "resolved": thread.resolved, "resolved_by": thread.resolved_by}

    @app.get(f"{API_PREFIX}/provenance/{{span_id}}/resolve")
    def provenance(span_id: str, session: SessionDep, actor: ActorDep) -> dict:
        span = session.scalar(
            select(ProvenanceSpan).where(
                ProvenanceSpan.id == span_id,
                ProvenanceSpan.clinic_id == actor.clinic_id,
            )
        )
        if span is None:
            raise conceal()
        entry = require_entry_read(session, actor, span.source_entry_id)
        try:
            resolved = resolve_span(session, span)
        except InvalidProvenanceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "invalid_provenance", "message": str(exc)},
            ) from exc
        return {
            "span_id": span.id,
            "source_entry_id": entry.id,
            "source_version_id": resolved.version.id,
            "source_version": resolved.version.version,
            "source_kind": span.source_kind,
            "source_uri": span.source_uri,
            "start_offset": span.start_offset,
            "end_offset": span.end_offset,
            "quote": span.quote,
            "content": resolved.version.content,
            "content_hash": resolved.version.content_hash,
            "verified": True,
        }

    @app.post(f"{API_PREFIX}/highlights/{{highlight_id}}/feedback")
    def highlight_feedback(
        highlight_id: str,
        payload: FeedbackRequest,
        session: SessionDep,
        actor: ActorDep,
    ) -> dict:
        require_internal_collaboration(actor)
        if actor.role not in {"staff", "clinician"}:
            raise forbidden("feedback_role_required")
        highlight = session.scalar(
            select(Highlight).where(
                Highlight.id == highlight_id,
                Highlight.clinic_id == actor.clinic_id,
            )
        )
        if highlight is None:
            raise conceal()
        patient = require_patient(session, actor, highlight.patient_id)
        record_feedback(
            session,
            actor=actor,
            highlight=highlight,
            action=payload.action,
            display_propensity=DETERMINISTIC_DISPLAY_PROPENSITY,
        )
        projection = _refresh_projection(session, patient)
        session.commit()
        return {
            "id": highlight.id,
            "status": highlight.status,
            "base_score": highlight.base_score,
            "adaptive_score": highlight.adaptive_score,
            "rank_score": highlight.rank_score,
            "projection_revision": projection.source_revision,
        }

    @app.post(f"{API_PREFIX}/scribe/ingest", status_code=201)
    def scribe_ingest(
        payload: ScribeIngestRequest,
        request: Request,
        session: SessionDep,
        actor: ActorDep,
    ) -> dict:
        patient = require_patient(session, actor, payload.patient_id)
        if actor.role == "patient" and payload.interaction_type != "patient_session":
            raise forbidden("patient_scribe_scope")
        if actor.role not in {"patient", "staff", "clinician"}:
            raise forbidden("scribe_role_required")
        system_actor = session.scalar(
            select(User).where(User.clinic_id == actor.clinic_id, User.role == "system")
        )
        if system_actor is None:
            raise HTTPException(status_code=503, detail="System author unavailable")
        try:
            result = ingest_scribe(
                session,
                initiating_actor=actor,
                system_actor=system_actor,
                patient=patient,
                interaction_type=payload.interaction_type,
                transcript=payload.transcript,
                source_uri=payload.source_uri,
                provider=request.app.state.scribe_provider,
            )
        except RedactionFidelityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "redaction_fidelity_failed",
                    "message": "The capture was withheld because clinical anchors changed.",
                },
            ) from exc
        detect_structured_conflicts(session, result.entry)
        _refresh_projection(session, patient)
        session.commit()
        return {
            "entry_id": result.entry.id,
            "status": "submitted_for_human_review",
            "provider": result.provider_name,
            "redaction_receipt": receipt_dict(result.receipt),
            "flags": result.flags,
        }

    @app.post(f"{API_PREFIX}/review/query")
    def evidence_review(
        payload: EvidenceReviewRequest,
        session: SessionDep,
        actor: ActorDep,
    ) -> dict:
        """Return a role-scoped answer whose clinical claims resolve to exact spans."""

        require_internal_collaboration(actor)
        patient = require_patient(session, actor, payload.patient_id)
        result = build_evidence_review(
            session,
            clinic_id=actor.clinic_id,
            patient_id=patient.id,
            question=payload.question,
        )
        append_audit(
            session,
            clinic_id=actor.clinic_id,
            actor_id=actor.id,
            action="evidence_review.generated",
            object_type="patient",
            object_id=patient.id,
            metadata={
                "intent": result.intent,
                "answer_state": result.answer_state,
                "claim_count": len(result.claims),
                "question_hash": sha256(payload.question.strip().encode("utf-8")).hexdigest(),
                "provider": result.provider,
            },
        )
        session.commit()
        return result.to_dict()

    @app.post(f"{API_PREFIX}/admin/retention/run")
    def retention_run(
        payload: RetentionRunRequest,
        session: SessionDep,
        actor: ActorDep,
    ) -> dict:
        require_admin(actor)
        as_of = datetime.fromisoformat(payload.as_of) if payload.as_of else datetime.now(UTC)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        manifests = apply_retention_policy(session, actor=actor, now=as_of)
        session.commit()
        return {
            "evaluated_at": _iso(as_of),
            "changes": [
                {
                    "id": item.id,
                    "entry_id": item.entry_id,
                    "from_tier": item.from_tier,
                    "to_tier": item.to_tier,
                    "reason": item.reason,
                    "source_hash": item.source_hash,
                    "dropped_derivatives": item.dropped_derivatives,
                }
                for item in manifests
            ],
        }

    @app.get(f"{API_PREFIX}/admin/audit/verify")
    def audit_verify(session: SessionDep, actor: ActorDep) -> dict:
        require_admin(actor)
        result = verify_audit_chain(session, actor.clinic_id)
        return asdict(result)

    @app.get(f"{API_PREFIX}/admin/audit/events")
    def audit_events(
        session: SessionDep,
        actor: ActorDep,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict:
        require_admin(actor)
        events = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.clinic_id == actor.clinic_id)
                .order_by(AuditEvent.sequence.desc())
                .limit(limit)
            )
        )
        return {
            "events": [
                {
                    "id": item.id,
                    "sequence": item.sequence,
                    "actor_id": item.actor_id,
                    "action": item.action,
                    "object_type": item.object_type,
                    "object_id": item.object_id,
                    "object_version": item.object_version,
                    "request_id": item.request_id,
                    "metadata": item.event_metadata,
                    "event_hash": item.event_hash,
                    "previous_hash": item.previous_hash,
                    "created_at": _iso(item.created_at),
                }
                for item in events
            ]
        }

    @app.get(f"{API_PREFIX}/research/policy-evaluation")
    def policy_evaluation(session: SessionDep, actor: ActorDep) -> dict:
        require_internal_collaboration(actor)
        return asdict(evaluate_shadow_policy(session, actor.clinic_id))

    return app


app = create_app()
