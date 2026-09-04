from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update

from app.configuration import (
    ClinicConfiguration,
    activate_configuration,
    active_configuration,
    configuration_hash,
    install_seed_configuration,
)
from app.database import Database
from app.models import AuditEvent, ClinicConfigVersion, User
from app.policy import resolve_actor
from app.seed import OTHER_CLINIC_ID, PRIMARY_CLINIC_ID, _ensure_demo_configurations

from .conftest import auth


def valid_configuration(**overrides) -> dict:
    payload = {
        "schema_version": "2026-09-01",
        "clinic_display_name": "Northstar Family Medicine",
        "timezone": "Asia/Singapore",
        "enabled_languages": ["en-SG", "ms-SG", "zh-SG"],
        "delivery_channels": ["whatsapp", "sms"],
        "features": {
            "streaming_capture": True,
            "multilingual_review": True,
            "outbound_delivery": True,
            "adaptive_ranking_shadow_only": True,
        },
        "safety": {
            "critical_risk_floor": 8.0,
            "provider_timeout_ms": 2000,
            "delivery_receipt_sla_minutes": 15,
            "require_dose_attestation": True,
        },
    }
    payload.update(overrides)
    return payload


def test_two_clinics_use_different_schema_valid_onboarding_configs(app) -> None:
    with app.state.database.session() as session:
        northstar = active_configuration(session, PRIMARY_CLINIC_ID)
        riverside = active_configuration(session, OTHER_CLINIC_ID)
        assert northstar is not None and riverside is not None
        northstar_config = ClinicConfiguration.model_validate(northstar.configuration)
        riverside_config = ClinicConfiguration.model_validate(riverside.configuration)

        assert northstar_config.timezone == "Asia/Singapore"
        assert northstar_config.delivery_channels == ["whatsapp", "sms"]
        assert riverside_config.timezone == "America/Los_Angeles"
        assert riverside_config.enabled_languages == ["en-US", "es-US"]
        assert riverside_config.delivery_channels == ["sms", "voice"]
        assert northstar.config_hash != riverside.config_hash


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"timezone": "Mars/Olympus"}, "IANA timezone"),
        ({"enabled_languages": ["not_a_tag"]}, "BCP 47"),
        ({"enabled_languages": ["en-SG", "EN-sg"]}, "duplicates"),
        ({"delivery_channels": ["sms", "sms"]}, "duplicates"),
        ({"unknown_setting": True}, "Extra inputs"),
        ({"schema_version": "2099-01-01"}, "Input should be"),
        (
            {"safety": {"critical_risk_floor": 7.9}},
            "greater than or equal to 8",
        ),
        (
            {"safety": {"provider_timeout_ms": 45001}},
            "less than or equal to 45000",
        ),
        (
            {"features": {"streaming_capture": "yes"}},
            "valid boolean",
        ),
    ],
)
def test_configuration_contract_rejects_drift_and_unsafe_values(override, message) -> None:
    with pytest.raises(ValidationError, match=message):
        ClinicConfiguration.model_validate(valid_configuration(**override))


def test_configuration_hash_is_canonical_and_change_sensitive() -> None:
    first = ClinicConfiguration.model_validate(valid_configuration())
    same = ClinicConfiguration.model_validate(valid_configuration())
    changed = ClinicConfiguration.model_validate(valid_configuration(delivery_channels=["voice"]))
    assert configuration_hash(first) == configuration_hash(same)
    assert configuration_hash(first) != configuration_hash(changed)
    assert len(configuration_hash(first)) == 64


def test_admin_schema_and_active_configuration_endpoints(client, identities) -> None:
    schema_response = client.get(
        "/api/v1/admin/clinic-config/schema",
        headers=auth(identities["admin"]),
    )
    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "2026-09-01"

    response = client.get(
        "/api/v1/admin/clinic-config",
        headers=auth(identities["admin"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["clinic_id"] == PRIMARY_CLINIC_ID
    assert body["revision"] == 1
    assert body["status"] == "active"
    assert body["activated_by"] is None
    assert body["configuration"]["enabled_languages"] == ["en-SG", "ms-SG", "zh-SG"]

    for path in (
        "/api/v1/admin/clinic-config/schema",
        "/api/v1/admin/clinic-config",
    ):
        denied = client.get(path, headers=auth(identities["clinician"]))
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "admin_required"


def test_activation_versions_audits_and_idempotently_reuses_same_hash(
    client, app, identities
) -> None:
    revised = valid_configuration(
        enabled_languages=["en-SG", "ms-SG", "zh-SG", "ta-SG"],
        delivery_channels=["whatsapp", "voice"],
    )
    first = client.post(
        "/api/v1/admin/clinic-config",
        headers=auth(identities["admin"]),
        json=revised,
    )
    assert first.status_code == 201
    revision = first.json()
    assert revision["revision"] == 2
    assert revision["activated_by"] == identities["admin"]

    repeated = client.post(
        "/api/v1/admin/clinic-config",
        headers=auth(identities["admin"]),
        json=revised,
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == revision["id"]
    assert repeated.json()["revision"] == 2

    current = client.get(
        "/api/v1/admin/clinic-config",
        headers=auth(identities["admin"]),
    )
    assert current.json()["configuration"] == revised

    with app.state.database.session() as session:
        records = list(
            session.scalars(
                select(ClinicConfigVersion)
                .where(ClinicConfigVersion.clinic_id == PRIMARY_CLINIC_ID)
                .order_by(ClinicConfigVersion.revision)
            )
        )
        assert [(item.revision, item.status) for item in records] == [
            (1, "superseded"),
            (2, "active"),
        ]
        audits = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == "clinic_configuration.activated")
            )
        )
        assert len(audits) == 1
        assert audits[0].event_metadata == {
            "config_revision": 2,
            "config_schema_version": "2026-09-01",
            "config_hash": revision["config_hash"],
        }


def test_activation_requires_admin_and_tenant_boundary_conceals_other_config(
    app, identities
) -> None:
    configuration = ClinicConfiguration.model_validate(valid_configuration())
    with app.state.database.session() as session:
        clinician = resolve_actor(session, identities["clinician"])
        with pytest.raises(PermissionError, match="administrator"):
            activate_configuration(
                session,
                actor=clinician,
                configuration=configuration,
            )
        assert (
            session.scalar(
                select(ClinicConfigVersion).where(ClinicConfigVersion.clinic_id == OTHER_CLINIC_ID)
            )
            is None
        )


def test_seed_install_is_idempotent_and_missing_active_config_fails_closed(
    client, app, identities
) -> None:
    with app.state.database.session() as session:
        existing = install_seed_configuration(
            session,
            clinic_id=PRIMARY_CLINIC_ID,
            configuration=ClinicConfiguration.model_validate(valid_configuration()),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert existing.revision == 1

        session.execute(
            update(ClinicConfigVersion)
            .where(ClinicConfigVersion.clinic_id == PRIMARY_CLINIC_ID)
            .values(status="superseded")
        )
        session.commit()

    response = client.get(
        "/api/v1/admin/clinic-config",
        headers=auth(identities["admin"]),
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "clinic_configuration_unavailable"


def test_activation_creates_revision_one_when_no_active_config(app, identities) -> None:
    with app.state.database.session() as session:
        admin = session.get(User, identities["admin"])
        assert admin is not None
        for record in session.scalars(
            select(ClinicConfigVersion).where(ClinicConfigVersion.clinic_id == PRIMARY_CLINIC_ID)
        ):
            session.delete(record)
        session.flush()

        created = activate_configuration(
            session,
            actor=admin,
            configuration=ClinicConfiguration.model_validate(valid_configuration()),
        )
        assert created.revision == 1
        assert created.status == "active"


def test_demo_configuration_installer_safely_handles_database_without_clinics() -> None:
    database = Database("sqlite://")
    database.create_all()
    with database.session() as session:
        _ensure_demo_configurations(session)
        assert list(session.scalars(select(ClinicConfigVersion))) == []
    database.engine.dispose()


def test_invalid_api_payload_is_rejected_before_activation(client, identities) -> None:
    denied_role = client.post(
        "/api/v1/admin/clinic-config",
        headers=auth(identities["clinician"]),
        json=valid_configuration(),
    )
    assert denied_role.status_code == 403

    invalid = client.post(
        "/api/v1/admin/clinic-config",
        headers=auth(identities["admin"]),
        json=valid_configuration(timezone="Singapore-ish", extra_switch=True),
    )
    assert invalid.status_code == 422
    error_locations = {tuple(item["loc"]) for item in invalid.json()["detail"]}
    assert ("body", "timezone") in error_locations
    assert ("body", "extra_switch") in error_locations
