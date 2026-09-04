"""Validate every request at the public API boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class RegenerateScribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=1)
    transcript: str = Field(min_length=1, max_length=50_000)
    source_uri: str = Field(min_length=4, max_length=300)

    @field_validator("source_uri")
    @classmethod
    def source_must_be_addressable(cls, value: str) -> str:
        if "://" not in value:
            raise ValueError("source_uri must include a URI scheme")
        return value


class StartCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    interaction_type: str = Field(pattern="^(doctor_consult|nurse_consult|patient_session)$")


class LanguageSpanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    language_tag: str = Field(pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    confidence: float = Field(ge=0.0, le=1.0)


class StreamSegmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    chunk_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$")
    sequence: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    speaker_label: str = Field(pattern="^(clinician|staff|patient|unknown|overlap)$")
    text: str = Field(min_length=1, max_length=5_000)
    language_spans: list[LanguageSpanRequest] = Field(min_length=1, max_length=24)
    asr_confidence: float = Field(ge=0.0, le=1.0)
    audio_quality: float = Field(ge=0.0, le=1.0)
    correction_of_segment_id: str | None = Field(default=None, min_length=3, max_length=64)

    @model_validator(mode="after")
    def validate_timeline_and_spans(self) -> StreamSegmentRequest:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        previous_end = 0
        for span in self.language_spans:
            if span.end_offset > len(self.text):
                raise ValueError("language span exceeds transcript text")
            if span.end_offset <= span.start_offset:
                raise ValueError("language span must have positive width")
            if span.start_offset < previous_end:
                raise ValueError("language spans must be sorted and non-overlapping")
            previous_end = span.end_offset
        return self


class SafetySignalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: str = Field(pattern="^(confirm|dismiss)$")
    rationale: str = Field(min_length=5, max_length=280)


class ResolveConflictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision: str = Field(pattern="^(confirm_left|confirm_right|escalate_unresolved)$")
    rationale: str = Field(min_length=8, max_length=220)
    confirm_sources_reviewed: bool


class EvidenceReviewRequest(BaseModel):
    patient_id: str
    question: str = Field(min_length=3, max_length=500)


class RetentionRunRequest(BaseModel):
    as_of: str | None = None


class QueueDeliveryRequest(BaseModel):
    contact_id: str = Field(min_length=3, max_length=64)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$")
    confirm_clinical_review: bool
    confirm_patient_identity: bool
    confirm_medication_and_dose: bool = False


class DeliveryTransitionRequest(BaseModel):
    outcome: str = Field(pattern="^(queued|accepted|delivered|failed)$")
    provider_message_id: str | None = Field(default=None, max_length=240)
    failure_code: str | None = Field(default=None, max_length=80)


class QueueCorrectionRequest(QueueDeliveryRequest):
    replacement_entry_id: str = Field(min_length=3, max_length=64)


class IssuePatientAccessClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contact_id: str = Field(min_length=1, max_length=64)
    purpose: str = Field(pattern="^(portal_access|intake|summary|instructions)$")
    ttl_minutes: int = Field(ge=5, le=15)


class RedeemPatientAccessClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claim_token: str = Field(min_length=20, max_length=100)
    synthetic_record_number: str = Field(min_length=4, max_length=32)
    date_of_birth: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    device_binding: str = Field(min_length=12, max_length=200)
