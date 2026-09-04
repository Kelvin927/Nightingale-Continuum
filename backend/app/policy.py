"""Enforce deny-by-default role, ownership, patient, and clinic policies."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .constants import CLINICIAN_APPROVED_PATIENT_ENTRY_TYPES, PATIENT_VISIBLE_ENTRY_TYPES
from .models import CommentThread, Entry, Patient, User
from .tenancy import bind_tenant


def conceal() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")


def forbidden(code: str = "action_not_permitted") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": "This action is not permitted for the current role."},
    )


def resolve_actor(session: Session, user_id: str | None) -> User:
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing demo identity"
        )
    actor = session.get(User, user_id)
    if actor is None or not actor.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid demo identity"
        )
    bind_tenant(session, actor.clinic_id)
    return actor


def require_patient(session: Session, actor: User, patient_id: str) -> Patient:
    patient = session.scalar(
        select(Patient).where(Patient.id == patient_id, Patient.clinic_id == actor.clinic_id)
    )
    if patient is None:
        raise conceal()
    if actor.role == "patient" and actor.patient_id != patient.id:
        raise conceal()
    return patient


def patient_can_read_entry(entry: Entry) -> bool:
    if entry.visibility != "patient" or entry.entry_type not in PATIENT_VISIBLE_ENTRY_TYPES:
        return False
    if entry.entry_type == "patient_insight":
        return entry.owner_role == "patient" and entry.author_id is not None
    return (
        entry.entry_type in CLINICIAN_APPROVED_PATIENT_ENTRY_TYPES
        and entry.owner_role == "clinician"
        and entry.trust_state == "clinician_confirmed"
    )


def require_entry_read(session: Session, actor: User, entry_id: str) -> Entry:
    entry = session.scalar(
        select(Entry).where(Entry.id == entry_id, Entry.clinic_id == actor.clinic_id)
    )
    if entry is None:
        raise conceal()
    require_patient(session, actor, entry.patient_id)
    if actor.role == "patient" and not patient_can_read_entry(entry):
        raise conceal()
    return entry


def require_entry_edit(session: Session, actor: User, entry_id: str) -> Entry:
    entry = require_entry_read(session, actor, entry_id)
    if actor.role not in {"patient", "staff", "clinician"}:
        raise forbidden("content_edit_disallowed")
    if entry.owner_role != actor.role:
        raise forbidden("cross_role_overwrite_denied")
    if actor.role == "patient" and entry.author_id != actor.id:
        raise forbidden("patient_entry_not_owned")
    return entry


def require_create_entry(actor: User, entry_type: str, visibility: str) -> None:
    allowed = {
        "patient": {"patient_insight"},
        "staff": {"staff_note", "patient_instruction", "admin_event"},
        "clinician": {"clinician_note", "patient_summary", "patient_instruction"},
        "admin": set(),
    }
    if entry_type not in allowed.get(actor.role, set()):
        raise forbidden("entry_type_not_permitted")
    if actor.role == "patient" and visibility != "patient":
        raise forbidden("patient_visibility_required")
    if actor.role == "staff" and visibility == "patient":
        raise forbidden("clinician_confirmation_required")
    if (
        actor.role == "clinician"
        and visibility == "patient"
        and entry_type not in CLINICIAN_APPROVED_PATIENT_ENTRY_TYPES
    ):
        raise forbidden("patient_entry_type_required")


def require_internal_collaboration(actor: User) -> None:
    if actor.role not in {"staff", "clinician", "admin"}:
        raise conceal()


def require_thread(session: Session, actor: User, thread_id: str) -> CommentThread:
    require_internal_collaboration(actor)
    thread = session.scalar(
        select(CommentThread).where(
            CommentThread.id == thread_id,
            CommentThread.clinic_id == actor.clinic_id,
        )
    )
    if thread is None:
        raise conceal()
    require_entry_read(session, actor, thread.entry_id)
    return thread


def require_admin(actor: User) -> None:
    if actor.role != "admin":
        raise forbidden("admin_required")


def can_view_internal(actor: User) -> bool:
    return actor.role in {"staff", "clinician", "admin"}
