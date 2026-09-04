import { ApiError, api } from "./api";

function response(payload: unknown, status = 200, statusText = "OK") {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: vi.fn().mockResolvedValue(payload),
  } as unknown as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ok: true })));
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-26T12:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("all API methods preserve paths, identity headers, methods, and JSON bodies", async () => {
  await api.identities();
  await api.me("user-1");
  await api.patients("user-1");
  await api.workspace("user-1", "patient-1");
  await api.glance("user-1", "patient-1");
  await api.delta("user-1", "patient-1");
  await api.provenance("user-1", "span-1");
  await api.feedback("user-1", "highlight-1", "pin");
  await api.createEntry("user-1", "patient-1", {
    entry_type: "clinician_note",
    title: "Title",
    content: "Content",
    visibility: "internal",
  });
  await api.editEntry("user-1", "entry-1", {
    content: "Revised",
    expected_version: 2,
    reason: "Correction",
  });
  await api.versions("user-1", "entry-1");
  await api.revert("user-1", "entry-1", 1, 2);
  await api.createThread("user-1", "entry-1", {
    title: "Review",
    body: "Please review",
    mentions: ["user-2"],
    assigned_to: "user-2",
  });
  await api.ingestScribe("user-1", {
    patient_id: "patient-1",
    interaction_type: "doctor_consult",
    transcript: "Synthetic transcript",
    source_uri: "session://synthetic/1",
  });
  await api.evidenceReview("user-1", "patient-1", "What changed?");
  await api.policyEvaluation("user-1");
  await api.auditVerification("user-1");
  await api.auditEvents("user-1");
  await api.runRetention("user-1");
  await api.deliveryReadiness("user-1", "patient-1");
  await api.queueDelivery("user-1", "entry-1", {
    contact_id: "contact-1",
    expected_version: 2,
    idempotency_key: "delivery-entry-1-v2",
    confirm_clinical_review: true,
    confirm_patient_identity: true,
    confirm_medication_and_dose: true,
  });
  await api.queueCorrection("user-1", "delivery-1", {
    replacement_entry_id: "entry-1",
    contact_id: "contact-1",
    expected_version: 3,
    idempotency_key: "correction-delivery-1-v3",
    confirm_clinical_review: true,
    confirm_patient_identity: true,
    confirm_medication_and_dose: true,
  });
  await api.transitionDelivery("user-1", "delivery-1", {
    outcome: "accepted",
    provider_message_id: "provider-1",
  });
  await api.startCapture("user-1", "patient-1", "doctor_consult");
  await api.appendCaptureSegment("user-1", "capture-1", {
    chunk_id: "chunk-1",
    sequence: 1,
    start_ms: 0,
    end_ms: 2_000,
    speaker_label: "patient",
    text: "Synthetic segment",
    language_spans: [
      { language_tag: "en-SG", start_offset: 0, end_offset: 17, confidence: 0.9 },
    ],
    asr_confidence: 0.9,
    audio_quality: 0.9,
    correction_of_segment_id: null,
  });
  await api.finalizeCapture("user-1", "capture-1");
  await api.reviewSafetySignal(
    "user-1",
    "signal-1",
    "confirm",
    "Confirmed with patient.",
  );
  await api.capture("user-1", "capture-1");
  await api.resolveConflict(
    "user-1",
    "conflict-1",
    "escalate_unresolved",
    "Both records require external reconciliation.",
    true,
  );

  const calls = vi.mocked(fetch).mock.calls;
  expect(calls).toHaveLength(29);
  expect(calls.map(([path]) => path)).toEqual([
    "/api/v1/demo/identities",
    "/api/v1/me",
    "/api/v1/patients",
    "/api/v1/patients/patient-1/workspace",
    "/api/v1/patients/patient-1/glance",
    "/api/v1/patients/patient-1/delta",
    "/api/v1/provenance/span-1/resolve",
    "/api/v1/highlights/highlight-1/feedback",
    "/api/v1/patients/patient-1/entries",
    "/api/v1/entries/entry-1",
    "/api/v1/entries/entry-1/versions",
    "/api/v1/entries/entry-1/revert",
    "/api/v1/entries/entry-1/comments",
    "/api/v1/scribe/ingest",
    "/api/v1/review/query",
    "/api/v1/research/policy-evaluation",
    "/api/v1/admin/audit/verify",
    "/api/v1/admin/audit/events?limit=30",
    "/api/v1/admin/retention/run",
    "/api/v1/patients/patient-1/delivery-readiness",
    "/api/v1/entries/entry-1/deliveries",
    "/api/v1/deliveries/delivery-1/corrections",
    "/api/v1/deliveries/delivery-1/transition",
    "/api/v1/patients/patient-1/captures",
    "/api/v1/captures/capture-1/segments",
    "/api/v1/captures/capture-1/finalize",
    "/api/v1/safety-signals/signal-1/review",
    "/api/v1/captures/capture-1",
    "/api/v1/conflicts/conflict-1/resolve",
  ]);
  expect((calls[0][1]?.headers as Headers).has("X-Demo-User")).toBe(false);
  expect((calls[1][1]?.headers as Headers).get("X-Demo-User")).toBe("user-1");
  expect((calls[1][1]?.headers as Headers).get("Content-Type")).toBe("application/json");
  expect(calls[7][1]).toMatchObject({ method: "POST", body: JSON.stringify({ action: "pin" }) });
  expect(calls[9][1]).toMatchObject({ method: "PATCH" });
  expect(calls[11][1]?.body).toBe(JSON.stringify({
    target_version: 1,
    expected_version: 2,
    reason: "Restore version 1 after review",
  }));
  expect(calls[14][1]).toMatchObject({
    method: "POST",
    body: JSON.stringify({ patient_id: "patient-1", question: "What changed?" }),
  });
  expect(calls[18][1]?.body).toBe(JSON.stringify({ as_of: "2026-08-26T12:00:00.000Z" }));
  expect(calls[20][1]).toMatchObject({ method: "POST" });
  expect(calls[21][1]?.body).toContain('"replacement_entry_id":"entry-1"');
  expect(calls[22][1]?.body).toBe(JSON.stringify({
    outcome: "accepted",
    provider_message_id: "provider-1",
  }));
  expect(calls[23][1]?.body).toBe(JSON.stringify({ interaction_type: "doctor_consult" }));
  expect(calls[24][1]?.body).toContain('"chunk_id":"chunk-1"');
  expect(calls[25][1]).toMatchObject({ method: "POST" });
  expect(calls[26][1]?.body).toBe(JSON.stringify({
    decision: "confirm",
    rationale: "Confirmed with patient.",
  }));
  expect(calls[28][1]).toMatchObject({
    method: "POST",
    body: JSON.stringify({
      decision: "escalate_unresolved",
      rationale: "Both records require external reconciliation.",
      confirm_sources_reviewed: true,
    }),
  });
});

test("API errors keep status and support string, object, and invalid JSON details", async () => {
  vi.mocked(fetch)
    .mockResolvedValueOnce(response({ detail: "Not allowed" }, 403, "Forbidden"))
    .mockResolvedValueOnce(response({ detail: { message: "Conflict" } }, 409, "Conflict"))
    .mockResolvedValueOnce({
      ...response({}, 500, "Server Error"),
      json: vi.fn().mockRejectedValue(new SyntaxError("invalid JSON")),
    } as unknown as Response);

  await expect(api.me("user-1")).rejects.toMatchObject({
    name: "Error",
    message: "Not allowed",
    status: 403,
    detail: "Not allowed",
  });
  await expect(api.me("user-1")).rejects.toMatchObject({
    message: "Request failed with status 409",
    detail: { message: "Conflict" },
  });
  await expect(api.me("user-1")).rejects.toMatchObject({
    message: "Server Error",
    status: 500,
    detail: "Server Error",
  });
  expect(new ApiError(400, "Bad request").message).toBe("Bad request");
});
