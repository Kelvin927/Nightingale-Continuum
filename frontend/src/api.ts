import type {
  AuditEvent,
  AuditVerification,
  DeltaLens,
  EvidenceReview,
  Glance,
  Identity,
  Patient,
  PolicyEvaluation,
  ResolvedProvenance,
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
  provenance: (userId: string, spanId: string) =>
    request<ResolvedProvenance>(`/api/v1/provenance/${spanId}/resolve`, userId),
  feedback: (
    userId: string,
    highlightId: string,
    action: "accept" | "reject" | "pin",
  ) =>
    request<{ status: string; adaptive_score: number; rank_score: number }>(
      `/api/v1/highlights/${highlightId}/feedback`,
      userId,
      {
        method: "POST",
        body: JSON.stringify({ action, display_propensity: 0.5 }),
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
      redaction_receipt: { detector_version: string; entity_counts: Record<string, number> };
      flags: string[];
    }>("/api/v1/scribe/ingest", userId, {
      method: "POST",
      body: JSON.stringify(payload),
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
