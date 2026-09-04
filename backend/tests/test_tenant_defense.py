from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import delete, select, text, update

from app.models import Base, Comment, EntryVersion, Patient
from app.policy import resolve_actor
from app.seed import OTHER_CLINIC_ID, OTHER_PATIENT_ID, PRIMARY_PATIENT_ID
from app.tenancy import TENANT_SCOPED_MODELS, TenantBoundaryError, bind_tenant


def test_unqualified_select_is_automatically_scoped_after_actor_resolution(app, identities) -> None:
    with app.state.database.session() as session:
        actor = resolve_actor(session, identities["clinician"])
        assert actor.clinic_id != OTHER_CLINIC_ID
        assert session.scalar(select(Patient).where(Patient.id == PRIMARY_PATIENT_ID)) is not None
        assert session.scalar(select(Patient).where(Patient.id == OTHER_PATIENT_ID)) is None
        assert all(
            patient.clinic_id == actor.clinic_id for patient in session.scalars(select(Patient))
        )


def test_session_cannot_rebind_or_flush_a_cross_tenant_object(app, identities) -> None:
    with app.state.database.session() as session:
        actor = resolve_actor(session, identities["clinician"])
        bind_tenant(session, actor.clinic_id)
        with pytest.raises(TenantBoundaryError, match="rebound"):
            bind_tenant(session, OTHER_CLINIC_ID)
        session.add(
            Patient(
                id="cross-tenant-write",
                clinic_id=OTHER_CLINIC_ID,
                display_name="Synthetic Cross Tenant",
                initials="CT",
                synthetic_record_number="SYN-CROSS-TENANT",
                date_of_birth="2000-01-01",
                pronouns="they/them",
                synthetic=True,
            )
        )
        with pytest.raises(TenantBoundaryError, match="does not match"):
            session.flush()
        session.rollback()


def test_bulk_mutations_are_scoped_or_denied_when_child_has_no_tenant_key(app, identities) -> None:
    with app.state.database.session() as session:
        resolve_actor(session, identities["clinician"])
        result = session.execute(
            update(Patient).values(pronouns="they/them").where(Patient.id == OTHER_PATIENT_ID)
        )
        assert result.rowcount == 0
        session.rollback()

    with app.state.database.session() as session:
        resolve_actor(session, identities["clinician"])
        assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        with pytest.raises(TenantBoundaryError, match="not tenant-addressable"):
            session.execute(delete(Comment).where(Comment.id == "synthetic-missing"))


def test_unbound_internal_session_remains_available_for_seed_and_migrations(app) -> None:
    with app.state.database.session() as session:
        assert session.scalar(select(Patient).where(Patient.id == OTHER_PATIENT_ID)) is not None


def test_postgres_rls_migration_forces_default_deny_on_every_table() -> None:
    root = Path(__file__).resolve().parents[2]
    sql = (root / "deployment/postgres/tenant_rls.sql").read_text(encoding="utf-8")
    assert "current_setting('app.clinic_id', true)" in sql
    assert "BYPASSRLS" in sql
    for table_name in Base.metadata.tables:
        assert f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;" in sql
        assert f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;" in sql

    inherited_tables = {EntryVersion.__tablename__, Comment.__tablename__}
    assert inherited_tables == {"entry_versions", "comments"}
    for table_name in inherited_tables:
        assert f"CREATE POLICY clinic_isolation ON {table_name}" in sql
        assert "EXISTS" in sql

    assert {model.__tablename__ for model in TENANT_SCOPED_MODELS} <= set(Base.metadata.tables)
