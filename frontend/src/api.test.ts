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

  const calls = vi.mocked(fetch).mock.calls;
  expect(calls).toHaveLength(19);
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
