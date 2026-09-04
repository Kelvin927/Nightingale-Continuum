"""Apply a second, session-wide tenant boundary beneath route-level policy checks."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from .models import (
    AuditEvent,
    CaptureSession,
    CareTask,
    ClinicConfigVersion,
    CommentThread,
    Conflict,
    Entry,
    FeaturePosterior,
    GlanceProjection,
    Highlight,
    ImportanceFeedback,
    OutboundDelivery,
    Patient,
    PatientContact,
    ProvenanceSpan,
    RetentionManifest,
    SafetySignal,
    TranscriptSegment,
    User,
)

TENANT_SESSION_KEY = "nightingale_clinic_id"
TENANT_SCOPED_MODELS = (
    AuditEvent,
    CareTask,
    CaptureSession,
    ClinicConfigVersion,
    CommentThread,
    Conflict,
    Entry,
    FeaturePosterior,
    GlanceProjection,
    Highlight,
    ImportanceFeedback,
    OutboundDelivery,
    Patient,
    PatientContact,
    ProvenanceSpan,
    RetentionManifest,
    SafetySignal,
    TranscriptSegment,
    User,
)


class TenantBoundaryError(RuntimeError):
    """Raised when one session attempts to cross or omit its bound clinic."""


def bind_tenant(session: Session, clinic_id: str) -> None:
    """Bind a session once; rebinding would turn a coding error into data exposure."""

    current = session.info.get(TENANT_SESSION_KEY)
    if current is not None and current != clinic_id:
        raise TenantBoundaryError("A database session cannot be rebound to another clinic")
    session.info[TENANT_SESSION_KEY] = clinic_id


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_boundary(execute_state: ORMExecuteState) -> None:
    clinic_id = execute_state.session.info.get(TENANT_SESSION_KEY)
    if clinic_id is None:
        return
    if execute_state.is_select:
        statement = execute_state.statement
        for model in TENANT_SCOPED_MODELS:
            statement = statement.options(
                with_loader_criteria(
                    model,
                    model.clinic_id == clinic_id,
                    include_aliases=True,
                )
            )
        execute_state.statement = statement
        return
    if execute_state.is_update or execute_state.is_delete:
        mapper = execute_state.bind_arguments.get("mapper")
        model = None if mapper is None else mapper.class_
        if model not in TENANT_SCOPED_MODELS:
            raise TenantBoundaryError("Bulk mutation is not tenant-addressable")
        execute_state.statement = execute_state.statement.where(model.clinic_id == clinic_id)


@event.listens_for(Session, "before_flush")
def _validate_tenant_writes(session: Session, _flush_context, _instances) -> None:
    clinic_id = session.info.get(TENANT_SESSION_KEY)
    if clinic_id is None:
        return
    pending = session.new.union(session.dirty).union(session.deleted)
    for instance in pending:
        if isinstance(instance, TENANT_SCOPED_MODELS) and instance.clinic_id != clinic_id:
            raise TenantBoundaryError("Tenant-scoped write does not match the bound clinic")
