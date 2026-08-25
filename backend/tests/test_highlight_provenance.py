from __future__ import annotations

from sqlalchemy import select

from app.models import Highlight, ProvenanceSpan

from .conftest import auth


def _all_highlights(glance: dict) -> list[dict]:
    return glance["groups"]["act_now"] + glance["groups"]["watch"]


def test_ai_highlight_has_resolvable_exact_span(client, identities, patient_id):
    glance_response = client.get(
        f"/api/v1/patients/{patient_id}/glance",
        headers=auth(identities["clinician"]),
    )
    assert glance_response.status_code == 200
    highlights = _all_highlights(glance_response.json())
    ai_highlight = next(item for item in highlights if item["trust_state"] == "ai_proposed")
    assert ai_highlight["provenance_span_id"]
    assert ai_highlight["risk_reason"]

    resolved = client.get(
        f"/api/v1/provenance/{ai_highlight['provenance_span_id']}/resolve",
        headers=auth(identities["clinician"]),
    )
    assert resolved.status_code == 200, resolved.text
    source = resolved.json()
    assert source["verified"] is True
    assert source["quote"] == source["content"][source["start_offset"] : source["end_offset"]]
    assert source["source_kind"].startswith("ai_")
    assert source["source_uri"].startswith("session://")


def test_broken_pointer_fails_closed(client, app, identities, patient_id):
    glance = client.get(
        f"/api/v1/patients/{patient_id}/glance",
        headers=auth(identities["clinician"]),
    ).json()
    highlight = _all_highlights(glance)[0]
    with app.state.database.session() as session:
        span = session.get(ProvenanceSpan, highlight["provenance_span_id"])
        assert span is not None
        span.quote = "tampered quote"
        session.commit()

    response = client.get(
        f"/api/v1/provenance/{highlight['provenance_span_id']}/resolve",
        headers=auth(identities["clinician"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "invalid_provenance"


def test_every_highlight_points_to_a_span(app):
    with app.state.database.session() as session:
        highlights = list(session.scalars(select(Highlight)))
        assert highlights
        for highlight in highlights:
            assert session.get(ProvenanceSpan, highlight.provenance_span_id) is not None
