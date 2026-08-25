from __future__ import annotations

from sqlalchemy import select

from app.models import Highlight

from .conftest import auth


def test_pinning_ai_highlight_increases_priority_for_similar_content(
    client, app, identities, patient_id
):
    with app.state.database.session() as session:
        candidates = list(
            session.scalars(
                select(Highlight).where(
                    Highlight.patient_id == patient_id,
                    Highlight.trust_state == "ai_proposed",
                )
            )
        )
        source = next(item for item in candidates if "medication" in item.entity_tags)
        target = next(
            item
            for item in session.scalars(
                select(Highlight).where(
                    Highlight.patient_id == patient_id,
                    Highlight.id != source.id,
                )
            )
            if "medication" in item.entity_tags
        )
        source_id = source.id
        target_id = target.id
        baseline_target = target.rank_score

    response = client.post(
        f"/api/v1/highlights/{source_id}/feedback",
        headers=auth(identities["clinician"]),
        json={"action": "pin", "display_propensity": 0.5},
    )
    assert response.status_code == 200, response.text

    with app.state.database.session() as session:
        learned_target = session.get(Highlight, target_id)
        pinned_source = session.get(Highlight, source_id)
        assert learned_target is not None
        assert pinned_source is not None
        assert learned_target.rank_score > baseline_target
        assert 0 < learned_target.adaptive_score <= 0.75
        assert pinned_source.status == "pinned"


def test_learning_cannot_displace_critical_safety_band(client, app, identities, patient_id):
    with app.state.database.session() as session:
        critical = next(
            item
            for item in session.scalars(select(Highlight).where(Highlight.patient_id == patient_id))
            if item.risk_level == "critical"
        )
        critical_id = critical.id

    glance = client.get(
        f"/api/v1/patients/{patient_id}/glance",
        headers=auth(identities["clinician"]),
    ).json()
    assert glance["groups"]["act_now"][0]["id"] == critical_id
    assert "outrank learned adjustments" in glance["safety_rule"]


def test_rejection_decreases_similar_priority_without_hiding_critical_safety(
    client, app, identities, patient_id
):
    with app.state.database.session() as session:
        candidates = list(
            session.scalars(select(Highlight).where(Highlight.patient_id == patient_id))
        )
        rejected_source = next(
            item
            for item in candidates
            if "follow_up" in item.entity_tags and item.risk_level != "critical"
        )
        similar_target = next(
            item
            for item in candidates
            if item.id != rejected_source.id and "follow_up" in item.entity_tags
        )
        critical = next(item for item in candidates if item.risk_level == "critical")
        rejected_source_id = rejected_source.id
        similar_target_id = similar_target.id
        critical_id = critical.id
        baseline_target = similar_target.rank_score

    response = client.post(
        f"/api/v1/highlights/{rejected_source_id}/feedback",
        headers=auth(identities["clinician"]),
        json={"action": "reject", "display_propensity": 0.5},
    )
    assert response.status_code == 200, response.text

    with app.state.database.session() as session:
        learned_target = session.get(Highlight, similar_target_id)
        rejected_source = session.get(Highlight, rejected_source_id)
        assert learned_target is not None
        assert rejected_source is not None
        assert learned_target.rank_score < baseline_target
        assert -0.75 <= learned_target.adaptive_score < 0
        assert rejected_source.status == "rejected"

    glance = client.get(
        f"/api/v1/patients/{patient_id}/glance",
        headers=auth(identities["clinician"]),
    ).json()
    assert glance["groups"]["act_now"][0]["id"] == critical_id
