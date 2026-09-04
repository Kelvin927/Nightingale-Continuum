"""Validate and version clinic onboarding configuration as an executable contract."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import append_audit
from .models import ClinicConfigVersion, User

CONFIG_SCHEMA_VERSION = "2026-09-01"
BCP47 = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z")


class FeatureConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    streaming_capture: bool = True
    multilingual_review: bool = True
    outbound_delivery: bool = True
    adaptive_ranking_shadow_only: bool = True


class SafetyConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    critical_risk_floor: float = Field(default=8.0, ge=8.0, le=20.0)
    provider_timeout_ms: int = Field(default=2_000, ge=250, le=45_000)
    delivery_receipt_sla_minutes: int = Field(default=15, ge=1, le=1_440)
    require_dose_attestation: bool = True


class ClinicConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["2026-09-01"] = CONFIG_SCHEMA_VERSION
    clinic_display_name: str = Field(min_length=2, max_length=160)
    timezone: str = Field(min_length=3, max_length=64)
    enabled_languages: list[str] = Field(min_length=1, max_length=8)
    delivery_channels: list[Literal["whatsapp", "sms", "voice", "email"]] = Field(
        min_length=1,
        max_length=4,
    )
    features: FeatureConfiguration = Field(default_factory=FeatureConfiguration)
    safety: SafetyConfiguration = Field(default_factory=SafetyConfiguration)

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be an IANA timezone") from exc
        return value

    @field_validator("enabled_languages")
    @classmethod
    def languages_must_be_unique_bcp47(cls, value: list[str]) -> list[str]:
        if any(not BCP47.fullmatch(item) for item in value):
            raise ValueError("enabled_languages must contain BCP 47 language tags")
        normalized = [item.lower() for item in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("enabled_languages must not contain duplicates")
        return value

    @field_validator("delivery_channels")
    @classmethod
    def channels_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("delivery_channels must not contain duplicates")
        return value


def configuration_hash(configuration: ClinicConfiguration) -> str:
    canonical = json.dumps(
        configuration.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def install_seed_configuration(
    session: Session,
    *,
    clinic_id: str,
    configuration: ClinicConfiguration,
    created_at: datetime,
) -> ClinicConfigVersion:
    existing = session.scalar(
        select(ClinicConfigVersion).where(ClinicConfigVersion.clinic_id == clinic_id)
    )
    if existing is not None:
        return existing
    record = ClinicConfigVersion(
        clinic_id=clinic_id,
        revision=1,
        schema_version=configuration.schema_version,
        configuration=configuration.model_dump(mode="json"),
        config_hash=configuration_hash(configuration),
        status="active",
        activated_by=None,
        created_at=created_at,
    )
    session.add(record)
    session.flush()
    return record


def active_configuration(session: Session, clinic_id: str) -> ClinicConfigVersion | None:
    return session.scalar(
        select(ClinicConfigVersion)
        .where(
            ClinicConfigVersion.clinic_id == clinic_id,
            ClinicConfigVersion.status == "active",
        )
        .order_by(ClinicConfigVersion.revision.desc())
    )


def activate_configuration(
    session: Session,
    *,
    actor: User,
    configuration: ClinicConfiguration,
) -> ClinicConfigVersion:
    if actor.role != "admin":
        raise PermissionError("Clinic configuration activation requires an administrator")
    digest = configuration_hash(configuration)
    current = active_configuration(session, actor.clinic_id)
    if current is not None and current.config_hash == digest:
        return current
    revision = 1 if current is None else current.revision + 1
    if current is not None:
        current.status = "superseded"
    record = ClinicConfigVersion(
        clinic_id=actor.clinic_id,
        revision=revision,
        schema_version=configuration.schema_version,
        configuration=configuration.model_dump(mode="json"),
        config_hash=digest,
        status="active",
        activated_by=actor.id,
        created_at=datetime.now(UTC),
    )
    session.add(record)
    session.flush()
    append_audit(
        session,
        clinic_id=actor.clinic_id,
        actor_id=actor.id,
        action="clinic_configuration.activated",
        object_type="clinic_config_version",
        object_id=record.id,
        object_version=record.revision,
        metadata={
            "config_revision": record.revision,
            "config_schema_version": record.schema_version,
            "config_hash": record.config_hash,
        },
    )
    return record


def serialize_configuration(record: ClinicConfigVersion) -> dict:
    return {
        "id": record.id,
        "clinic_id": record.clinic_id,
        "revision": record.revision,
        "schema_version": record.schema_version,
        "configuration": record.configuration,
        "config_hash": record.config_hash,
        "status": record.status,
        "activated_by": record.activated_by,
        "created_at": record.created_at.isoformat(),
    }
