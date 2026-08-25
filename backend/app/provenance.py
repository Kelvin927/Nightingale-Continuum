from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .care import content_hash
from .models import Entry, EntryVersion, ProvenanceSpan


class InvalidProvenanceError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedProvenance:
    span: ProvenanceSpan
    entry: Entry
    version: EntryVersion


def create_span(
    session: Session,
    *,
    entry: Entry,
    version: EntryVersion,
    start_offset: int,
    end_offset: int,
    source_kind: str | None = None,
    source_uri: str | None = None,
) -> ProvenanceSpan:
    if version.entry_id != entry.id:
        raise InvalidProvenanceError("Version does not belong to entry")
    if start_offset < 0 or end_offset <= start_offset or end_offset > len(version.content):
        raise InvalidProvenanceError("Span offsets are out of bounds")
    quote = version.content[start_offset:end_offset]
    if not quote.strip():
        raise InvalidProvenanceError("Span cannot be blank")
    span = ProvenanceSpan(
        clinic_id=entry.clinic_id,
        patient_id=entry.patient_id,
        source_entry_id=entry.id,
        source_version_id=version.id,
        start_offset=start_offset,
        end_offset=end_offset,
        quote=quote,
        source_content_hash=version.content_hash,
        source_kind=source_kind or entry.entry_type,
        source_uri=source_uri
        or entry.source_uri
        or f"entry://{entry.id}/versions/{version.version}",
    )
    session.add(span)
    session.flush()
    return span


def resolve_span(session: Session, span: ProvenanceSpan) -> ResolvedProvenance:
    entry = session.get(Entry, span.source_entry_id)
    version = session.get(EntryVersion, span.source_version_id)
    if entry is None or version is None:
        raise InvalidProvenanceError("Source object is missing")
    if entry.clinic_id != span.clinic_id or entry.patient_id != span.patient_id:
        raise InvalidProvenanceError("Source scope does not match span scope")
    if version.entry_id != entry.id:
        raise InvalidProvenanceError("Source version does not belong to source entry")
    if content_hash(version.content) != version.content_hash:
        raise InvalidProvenanceError("Source content hash is invalid")
    if version.content_hash != span.source_content_hash:
        raise InvalidProvenanceError("Source content changed after anchoring")
    if span.start_offset < 0 or span.end_offset > len(version.content):
        raise InvalidProvenanceError("Stored span is out of bounds")
    if version.content[span.start_offset : span.end_offset] != span.quote:
        raise InvalidProvenanceError("Stored quote does not match source span")
    return ResolvedProvenance(span, entry, version)
