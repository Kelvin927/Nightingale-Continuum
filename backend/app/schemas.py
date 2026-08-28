"""Validate every request at the public API boundary."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CreateEntryRequest(BaseModel):
    entry_type: str = Field(min_length=3, max_length=64)
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=1, max_length=30_000)
    visibility: str = Field(pattern="^(internal|patient)$")


class EditEntryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=30_000)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=240)


class RevertEntryRequest(BaseModel):
    target_version: int = Field(ge=1)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=240)


class CreateThreadRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=1, max_length=5_000)
    mentions: list[str] = Field(default_factory=list, max_length=12)
    assigned_to: str | None = None


class CreateCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=5_000)
    mentions: list[str] = Field(default_factory=list, max_length=12)
    assigned_to: str | None = None


class ResolveThreadRequest(BaseModel):
    resolved: bool


class FeedbackRequest(BaseModel):
    action: str = Field(pattern="^(accept|reject|pin)$")


class ScribeIngestRequest(BaseModel):
    patient_id: str
    interaction_type: str = Field(pattern="^(doctor_consult|nurse_consult|patient_session)$")
    transcript: str = Field(min_length=1, max_length=50_000)
    source_uri: str = Field(min_length=4, max_length=300)

    @field_validator("source_uri")
    @classmethod
    def source_must_be_addressable(cls, value: str) -> str:
        if "://" not in value:
            raise ValueError("source_uri must include a URI scheme")
        return value


class EvidenceReviewRequest(BaseModel):
    patient_id: str
    question: str = Field(min_length=3, max_length=500)


class RetentionRunRequest(BaseModel):
    as_of: str | None = None
