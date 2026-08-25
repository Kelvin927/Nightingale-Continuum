from __future__ import annotations

from app import main as main_module
from app.models import AuditEvent, Entry, GlanceProjection, Highlight, ProvenanceSpan
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from .conftest import auth


def _transactional_counts(app, patient_id: str) -> tuple[int, int, int, int, int]:
    with app.state.database.session() as session:
        return (
            session.scalar(select(func.count(Entry.id)).where(Entry.patient_id == patient_id)),
            session.scalar(
                select(func.count(Highlight.id)).where(Highlight.patient_id == patient_id)
            ),
            session.scalar(
                select(func.count(ProvenanceSpan.id)).where(ProvenanceSpan.patient_id == patient_id)
            ),
            session.scalar(select(func.count(AuditEvent.id))),
            session.scalar(
                select(GlanceProjection.source_revision).where(
                    GlanceProjection.patient_id == patient_id
                )
            ),
        )


def test_scribe_transaction_rolls_back_every_partial_write_when_projection_refresh_fails(
    app, identities, patient_id, monkeypatch
):
    before = _transactional_counts(app, patient_id)

    def fail_projection(*_args, **_kwargs):
        raise RuntimeError("Injected projection failure")

    monkeypatch.setattr(main_module, "_refresh_projection", fail_projection)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/scribe/ingest",
            headers=auth(identities["clinician"]),
            json={
                "patient_id": patient_id,
                "interaction_type": "doctor_consult",
                "transcript": (
                    "Synthetic patient reports medication follow-up after a clinician review."
                ),
                "source_uri": "session://failure-injection/rollback",
            },
        )

    assert response.status_code == 500
    assert _transactional_counts(app, patient_id) == before
