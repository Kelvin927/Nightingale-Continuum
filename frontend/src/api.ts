import type {
  AuditEvent,
  AuditVerification,
  ConflictItem,
  DeltaLens,
  DeliveryItem,
  DeliveryReadiness,
  EvidenceReview,
  Glance,
  Identity,
  LanguageSpan,
  Patient,
  PatientAccessClaim,
  PatientAccessGrant,
  PolicyEvaluation,
  ResolvedProvenance,
  RegenerationResult,
  SafetySignal,
  StreamingCapture,
  Viewer,
  Workspace,
} from "./types";

// This client sends only identity and object identifiers; role and clinic scope
// are always re-derived and enforced by the API.

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed with status ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, userId?: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (userId) headers.set("X-Demo-User", userId);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, payload.detail);
  }
  return response.json() as Promise<T>;
}

async function patientSessionRequest<T>(
  path: string,
  sessionToken: string,
  deviceBinding: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  headers.set("X-Patient-Session", sessionToken);
  headers.set("X-Patient-Device", deviceBinding);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, payload.detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  identities: () =>
    request<{ warning: string; identities: Identity[] }>("/api/v1/demo/identities"),
  me: (userId: string) => request<Viewer>("/api/v1/me", userId),
  patients: (userId: string) =>
    request<{ patients: Patient[] }>("/api/v1/patients", userId),
  workspace: (userId: string, patientId: string) =>
    request<Workspace>(`/api/v1/patients/${patientId}/workspace`, userId),
  glance: (userId: string, patientId: string) =>
    request<Glance>(`/api/v1/patients/${patientId}/glance`, userId),
  delta: (userId: string, patientId: string) =>
    request<DeltaLens>(`/api/v1/patients/${patientId}/delta`, userId),
  deliveryReadiness: (userId: string, patientId: string) =>
    request<DeliveryReadiness>(
      `/api/v1/patients/${patientId}/delivery-readiness`,
      userId,
    ),
  issuePatientAccess: (
    userId: string,
    patientId: string,
    payload: {
      contact_id: string;
      purpose: PatientAccessClaim["purpose"];
      ttl_minutes: number;
    },
  ) =>
    request<PatientAccessClaim>(
      `/api/v1/patients/${patientId}/access-claims`,
      userId,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  redeemPatientAccess: (payload: {
    claim_token: string;
    synthetic_record_number: string;
    date_of_birth: string;
    device_binding: string;
  }) =>
    request<PatientAccessGrant>("/api/v1/patient-access/redeem", undefined, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  patientSessionMe: (sessionToken: string, deviceBinding: string) =>
    patientSessionRequest<Viewer>("/api/v1/me", sessionToken, deviceBinding),
  patientSessionWorkspace: (
    sessionToken: string,
    deviceBinding: string,
    patientId: string,
  ) =>
    patientSessionRequest<Workspace>(
      `/api/v1/patients/${patientId}/workspace`,
      sessionToken,
      deviceBinding,
    ),
  queueDelivery: (
    userId: string,
    entryId: string,
    payload: {
      contact_id: string;
      expected_version: number;
      idempotency_key: string;
      confirm_clinical_review: boolean;
      confirm_patient_identity: boolean;
      confirm_medication_and_dose: boolean;
      communication_purpose: DeliveryItem["communication_purpose"];
      confirm_appointment_details: boolean;
      acknowledgement_window_minutes: number;
    },
  ) =>
    request<DeliveryReadiness>(`/api/v1/entries/${entryId}/deliveries`, userId, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  queueCorrection: (
    userId: string,
    deliveryId: string,
    payload: {
      replacement_entry_id: string;
      contact_id: string;
      expected_version: number;
      idempotency_key: string;
      confirm_clinical_review: boolean;
      confirm_patient_identity: boolean;
      confirm_medication_and_dose: boolean;
      communication_purpose: DeliveryItem["communication_purpose"];
      confirm_appointment_details: boolean;
      acknowledgement_window_minutes: number;
    },
  ) =>
    request<DeliveryReadiness>(
      `/api/v1/deliveries/${deliveryId}/corrections`,
      userId,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  transitionDelivery: (
    userId: string,
    deliveryId: string,
    payload: {
      outcome: "queued" | "accepted" | "delivered" | "failed";
      provider_message_id?: string;
      failure_code?: string;
    },
  ) =>
    request<DeliveryReadiness>(
      `/api/v1/deliveries/${deliveryId}/transition`,
      userId,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  acknowledgeDelivery: (userId: string, deliveryId: string) =>
    request<DeliveryReadiness>(
      `/api/v1/deliveries/${deliveryId}/acknowledge`,
      userId,
      { method: "POST" },
    ),
  escalateDeliveryFollowUps: (userId: string, patientId: string) =>
    request<DeliveryReadiness>(
      `/api/v1/patients/${patientId}/delivery-follow-ups/escalate`,
      userId,
      { method: "POST", body: JSON.stringify({}) },
    ),
  provenance: (userId: string, spanId: string) =>
    request<ResolvedProvenance>(`/api/v1/provenance/${spanId}/resolve`, userId),
  feedback: (
    userId: string,
    highlightId: string,
    action: "accept" | "reject" | "pin",
  ) =>
    request<{
      status: string;
      adaptive_score: number;
      shadow_adaptive_score: number;
      rank_score: number;
      ranking_mode: "fixed_safety_with_shadow_learning";
    }>(
      `/api/v1/highlights/${highlightId}/feedback`,
      userId,
      {
        method: "POST",
        body: JSON.stringify({ action }),
      },
    ),
  createEntry: (
    userId: string,
    patientId: string,
    payload: { entry_type: string; title: string; content: string; visibility: string },
  ) =>
    request(`/api/v1/patients/${patientId}/entries`, userId, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  editEntry: (
    userId: string,
    entryId: string,
    payload: { content: string; expected_version: number; reason: string },
  ) =>
    request(`/api/v1/entries/${entryId}`, userId, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  versions: (userId: string, entryId: string) =>
    request<{ entry_id: string; current_version: number; versions: Workspace["entries"][number]["version"][] }>(
      `/api/v1/entries/${entryId}/versions`,
      userId,
    ),
  revert: (
    userId: string,
    entryId: string,
    targetVersion: number,
    expectedVersion: number,
  ) =>
    request(`/api/v1/entries/${entryId}/revert`, userId, {
      method: "POST",
      body: JSON.stringify({
        target_version: targetVersion,
        expected_version: expectedVersion,
        reason: `Restore version ${targetVersion} after review`,
      }),
    }),
  createThread: (
    userId: string,
    entryId: string,
    payload: { title: string; body: string; mentions: string[]; assigned_to: string | null },
  ) =>
    request(`/api/v1/entries/${entryId}/comments`, userId, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  ingestScribe: (
    userId: string,
    payload: {
      patient_id: string;
      interaction_type: string;
      transcript: string;
      source_uri: string;
    },
  ) =>
    request<{
      entry_id: string;
      status: string;
      provider: string;
      provider_status: string;
      provider_failure_code: string | null;
      redaction_receipt: {
        detector_version: string;
        entity_counts: Record<string, number>;
        clinical_anchor_count: number;
        clinical_anchors_preserved: boolean;
        passed: boolean;
      };
      flags: string[];
    }>("/api/v1/scribe/ingest", userId, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  regenerateScribe: (
    userId: string,
    entryId: string,
    payload: { expected_version: number; transcript: string; source_uri: string },
  ) =>
    request<RegenerationResult>(`/api/v1/entries/${entryId}/regenerate`, userId, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  startCapture: (userId: string, patientId: string, interactionType: string) =>
    request<StreamingCapture>(`/api/v1/patients/${patientId}/captures`, userId, {
      method: "POST",
      body: JSON.stringify({ interaction_type: interactionType }),
    }),
  appendCaptureSegment: (
    userId: string,
    captureId: string,
    payload: {
      chunk_id: string;
      sequence: number;
      start_ms: number;
      end_ms: number;
      speaker_label: "clinician" | "staff" | "patient" | "unknown" | "overlap";
      text: string;
      language_spans: LanguageSpan[];
      asr_confidence: number;
      audio_quality: number;
      correction_of_segment_id: string | null;
    },
  ) =>
    request<StreamingCapture>(`/api/v1/captures/${captureId}/segments`, userId, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  finalizeCapture: (userId: string, captureId: string) =>
    request<StreamingCapture>(`/api/v1/captures/${captureId}/finalize`, userId, {
      method: "POST",
    }),
  reviewSafetySignal: (
    userId: string,
    signalId: string,
    decision: "confirm" | "dismiss",
    rationale: string,
  ) =>
    request<SafetySignal>(`/api/v1/safety-signals/${signalId}/review`, userId, {
      method: "POST",
      body: JSON.stringify({ decision, rationale }),
    }),
  capture: (userId: string, captureId: string) =>
    request<StreamingCapture>(`/api/v1/captures/${captureId}`, userId),
  resolveConflict: (
    userId: string,
    conflictId: string,
    decision: "confirm_left" | "confirm_right" | "escalate_unresolved",
    rationale: string,
    confirmSourcesReviewed: boolean,
  ) =>
    request<ConflictItem>(`/api/v1/conflicts/${conflictId}/resolve`, userId, {
      method: "POST",
      body: JSON.stringify({
        decision,
        rationale,
        confirm_sources_reviewed: confirmSourcesReviewed,
      }),
    }),
  evidenceReview: (userId: string, patientId: string, question: string) =>
    request<EvidenceReview>("/api/v1/review/query", userId, {
      method: "POST",
      body: JSON.stringify({ patient_id: patientId, question }),
    }),
  policyEvaluation: (userId: string) =>
    request<PolicyEvaluation>("/api/v1/research/policy-evaluation", userId),
  auditVerification: (userId: string) =>
    request<AuditVerification>("/api/v1/admin/audit/verify", userId),
  auditEvents: (userId: string) =>
    request<{ events: AuditEvent[] }>("/api/v1/admin/audit/events?limit=30", userId),
  runRetention: (userId: string) =>
    request<{ evaluated_at: string; changes: unknown[] }>("/api/v1/admin/retention/run", userId, {
      method: "POST",
      body: JSON.stringify({ as_of: new Date().toISOString() }),
    }),
};
