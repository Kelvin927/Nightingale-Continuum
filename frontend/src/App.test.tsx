import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("./api", () => {
  class MockApiError extends Error {
    status: number;
    detail: unknown;

    constructor(status: number, detail: unknown) {
      super(typeof detail === "string" ? detail : `Request failed with status ${status}`);
      this.status = status;
      this.detail = detail;
    }
  }

  return {
    ApiError: MockApiError,
    api: {
      identities: vi.fn(),
      me: vi.fn(),
      patients: vi.fn(),
      workspace: vi.fn(),
      glance: vi.fn(),
      delta: vi.fn(),
      provenance: vi.fn(),
      feedback: vi.fn(),
      createEntry: vi.fn(),
      editEntry: vi.fn(),
      versions: vi.fn(),
      revert: vi.fn(),
      createThread: vi.fn(),
      ingestScribe: vi.fn(),
      evidenceReview: vi.fn(),
      policyEvaluation: vi.fn(),
      auditVerification: vi.fn(),
      auditEvents: vi.fn(),
      runRetention: vi.fn(),
    },
  };
});

import App from "./App";
import { ApiError, api } from "./api";
import {
  auditEvents,
  delta,
  evidenceReview,
  evaluation,
  glance,
  identities,
  patient,
  patientGlance,
  provenance,
  verification,
  versionOne,
  versionTwo,
  viewer,
  workspace,
} from "./test/fixtures";
import type { Role } from "./types";

const mockedApi = vi.mocked(api);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function roleFor(userId: string): Role {
  return identities.find((identity) => identity.id === userId)?.role ?? "clinician";
}

function configureSuccessApi() {
  mockedApi.identities.mockResolvedValue({ warning: "Synthetic identities", identities });
  mockedApi.me.mockImplementation(async (userId) => viewer(roleFor(userId)));
  mockedApi.patients.mockResolvedValue({
    patients: [
      patient,
      {
        ...patient,
        id: "patient-2",
        display_name: "Jon Tan",
        initials: "JT",
        synthetic_record_number: "SYN-0002",
      },
    ],
  });
  mockedApi.workspace.mockImplementation(async (userId) => ({
    ...workspace,
    viewer: { id: userId, role: roleFor(userId) },
    entries: roleFor(userId) === "patient" ? [workspace.entries[2]] : workspace.entries,
  }));
  mockedApi.glance.mockImplementation(async (userId) =>
    roleFor(userId) === "patient" ? patientGlance : glance,
  );
  mockedApi.delta.mockResolvedValue(delta);
  mockedApi.provenance.mockResolvedValue(provenance);
  mockedApi.feedback.mockResolvedValue({ status: "accepted", adaptive_score: 0.1, rank_score: 8.5 });
  mockedApi.createEntry.mockResolvedValue({});
  mockedApi.editEntry.mockResolvedValue({});
  mockedApi.versions.mockResolvedValue({
    entry_id: "entry-clinician",
    current_version: 2,
    versions: [versionOne, versionTwo],
  });
  mockedApi.revert.mockResolvedValue({});
  mockedApi.createThread.mockResolvedValue({});
  mockedApi.ingestScribe.mockResolvedValue({
    entry_id: "entry-scribe",
    status: "proposed",
    provider: "local-deterministic",
    redaction_receipt: {
      detector_version: "continuum-redactor-v1",
      entity_counts: { PERSON: 1 },
      clinical_anchor_count: 3,
      clinical_anchors_preserved: true,
      passed: true,
    },
    flags: ["human_review_required"],
  });
  mockedApi.evidenceReview.mockResolvedValue(evidenceReview);
  mockedApi.policyEvaluation.mockResolvedValue(evaluation);
  mockedApi.auditVerification.mockResolvedValue(verification);
  mockedApi.auditEvents.mockResolvedValue({ events: auditEvents });
  mockedApi.runRetention.mockResolvedValue({ evaluated_at: "2026-08-26T12:00:00Z", changes: [{ id: "entry-1" }] });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  configureSuccessApi();
});

async function renderFor(userId: string) {
  localStorage.setItem("continuum-demo-user", userId);
  render(<App />);
  expect(screen.getByLabelText("Loading care note")).toBeVisible();
  await screen.findByRole("heading", { name: "Maya Chen" });
}

// This end-to-end component journey covers more than thirty UI and API interactions.
// The explicit outer bound absorbs CI scheduling variance; each async assertion keeps
// its shorter Testing Library deadline and still fails close to the responsible action.
const FULL_CLINICIAN_WORKFLOW_TIMEOUT_MS = 15_000;

test("clinician workflow completes evidence review, provenance, notes, threads, history, scribe, and role switching", async () => {
  await renderFor("user-clinician");

  fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
  expect(screen.getByText("Navigate")).toBeVisible();
  fireEvent.click(document.querySelector<HTMLButtonElement>(".sidebar-mobile-heading button")!);
  fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
  fireEvent.click(screen.getByRole("button", { name: "Close navigation" }));

  fireEvent.click(screen.getByRole("button", { name: /policy lab/i }));
  expect(await screen.findByText("72.0%")).toBeVisible();
  expect(mockedApi.policyEvaluation).toHaveBeenCalledWith("user-clinician");
  fireEvent.click(screen.getByRole("button", { name: /care note/i }));
  fireEvent.click(screen.getByRole("button", { name: /related note/i }));
  fireEvent.click(screen.getByRole("button", { name: /review evidence/i }));

  fireEvent.click(screen.getByRole("button", { name: /^evidence review$/i }));
  fireEvent.click(screen.getByRole("button", { name: "Which medication evidence conflicts?" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /^review evidence$/i }));
  await waitFor(() => expect(mockedApi.evidenceReview).toHaveBeenCalledWith(
    "user-clinician",
    patient.id,
    "Which medication evidence conflicts?",
  ));
  expect(await screen.findByText(evidenceReview.summary)).toBeVisible();
  expect(screen.getByText(evidenceReview.claims[0].quote)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /open source entry/i }));
  expect(document.querySelector("#entry-entry-clinician")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: /^evidence review$/i }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /^review evidence$/i }));
  expect(await screen.findByText(evidenceReview.summary)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /verify exact source/i }));
  expect(await screen.findByRole("heading", { name: "Verified exact source" })).toBeVisible();
  fireEvent.click(screen.getAllByRole("button", { name: "Close source drawer" })[1]);

  fireEvent.click(screen.getAllByRole("button", { name: /exact source/i })[0]);
  expect(await screen.findByRole("heading", { name: "Verified exact source" })).toBeVisible();
  fireEvent.click(screen.getAllByRole("button", { name: "Close source drawer" })[1]);

  fireEvent.click(screen.getByRole("button", { name: "Accept" }));
  await waitFor(() => expect(mockedApi.feedback).toHaveBeenCalledWith(
    "user-clinician",
    "highlight-1",
    "accept",
  ));
  expect(await screen.findByRole("status")).toHaveTextContent("Accept recorded");

  fireEvent.click(screen.getByRole("button", { name: /add note/i }));
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "New evidence" } });
  fireEvent.change(screen.getByLabelText("Note content"), { target: { value: "A reviewed clinical update." } });
  fireEvent.click(screen.getByRole("button", { name: /save version/i }));
  await waitFor(() => expect(mockedApi.createEntry).toHaveBeenCalledWith(
    "user-clinician",
    patient.id,
    {
      entry_type: "clinician_note",
      title: "New evidence",
      content: "A reviewed clinical update.",
      visibility: "internal",
    },
  ));

  fireEvent.click(screen.getByRole("button", { name: /edit section/i }));
  fireEvent.change(screen.getByLabelText("Note content"), { target: { value: "Corrected immutable content." } });
  fireEvent.click(screen.getByRole("button", { name: /save version/i }));
  await waitFor(() => expect(mockedApi.editEntry).toHaveBeenCalledWith(
    "user-clinician",
    "entry-clinician",
    expect.objectContaining({ content: "Corrected immutable content.", expected_version: 1 }),
  ));

  const clinicalCard = screen.getByRole("article", { name: /assessment and plan/i });
  fireEvent.click(within(clinicalCard).getByRole("button", { name: /1 thread/i }));
  fireEvent.click(within(clinicalCard).getByRole("button", { name: /start another thread/i }));
  fireEvent.change(screen.getByLabelText("Comment"), { target: { value: "Please verify today." } });
  fireEvent.click(screen.getByLabelText(/assign to nurse noor/i));
  fireEvent.click(screen.getByRole("button", { name: /post thread/i }));
  await waitFor(() => expect(mockedApi.createThread).toHaveBeenCalledWith(
    "user-clinician",
    "entry-clinician",
    expect.objectContaining({ assigned_to: "user-staff", mentions: ["user-staff"] }),
  ));
  fireEvent.click(within(clinicalCard).getByRole("button", { name: /start another thread/i }));
  fireEvent.change(screen.getByLabelText("Comment"), { target: { value: "Unassigned review." } });
  fireEvent.click(screen.getByRole("button", { name: /post thread/i }));
  await waitFor(() => expect(mockedApi.createThread).toHaveBeenLastCalledWith(
    "user-clinician",
    "entry-clinician",
    expect.objectContaining({ assigned_to: null, mentions: [] }),
  ));

  fireEvent.click(within(clinicalCard).getByRole("button", { name: /version 1/i }));
  expect(await screen.findByRole("heading", { name: "Revision history" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /restore/i }));
  await waitFor(() => expect(mockedApi.revert).toHaveBeenCalledWith(
    "user-clinician",
    "entry-clinician",
    2,
    1,
  ));

  fireEvent.click(screen.getByRole("button", { name: /capture consult/i }));
  fireEvent.click(screen.getByRole("button", { name: /create review draft/i }));
  expect(await screen.findByText("Draft submitted for human review")).toBeVisible();
  expect(mockedApi.ingestScribe).toHaveBeenCalledWith(
    "user-clinician",
    expect.objectContaining({ patient_id: patient.id, interaction_type: "doctor_consult" }),
  );
  fireEvent.click(screen.getByRole("button", { name: /return to care note/i }));

  fireEvent.click(screen.getByRole("button", { name: /dr lina.*clinician/i }));
  fireEvent.click(screen.getByRole("button", { name: /nurse noor.*staff/i }));
  await waitFor(() => expect(mockedApi.me).toHaveBeenCalledWith("user-staff"));
  expect(localStorage.getItem("continuum-demo-user")).toBe("user-staff");
  expect((await screen.findAllByText("Nurse Noor"))[0]).toBeVisible();
}, FULL_CLINICIAN_WORKFLOW_TIMEOUT_MS);

test("admin workflow verifies audit integrity and runs retention with a refreshed evidence view", async () => {
  await renderFor("user-admin");
  expect(screen.queryByRole("button", { name: /add note/i })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /trust ops/i }));
  expect(await screen.findByText("Audit chain verified")).toBeVisible();
  expect(mockedApi.auditVerification).toHaveBeenCalledWith("user-admin");
  fireEvent.click(screen.getByRole("button", { name: /run retention policy/i }));
  await waitFor(() => expect(mockedApi.runRetention).toHaveBeenCalledWith("user-admin"));
  expect(await screen.findByRole("status")).toHaveTextContent("1 tier changes recorded");
  await waitFor(() => expect(mockedApi.auditEvents).toHaveBeenCalledTimes(2));
});

test("admin retention remains available without an assigned patient and skips care refresh", async () => {
  localStorage.setItem("continuum-demo-user", "user-admin");
  mockedApi.patients.mockResolvedValueOnce({ patients: [] });
  render(<App />);
  const trustOps = await screen.findByRole("button", { name: /trust ops/i });
  fireEvent.click(trustOps);
  expect(await screen.findByText("Audit chain verified")).toBeVisible();
  const workspaceCalls = mockedApi.workspace.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: /run retention policy/i }));
  await waitFor(() => expect(mockedApi.runRetention).toHaveBeenCalledWith("user-admin"));
  expect(mockedApi.workspace).toHaveBeenCalledTimes(workspaceCalls);
});

test("patient mode skips internal delta and research while preserving patient-owned contribution and capture", async () => {
  await renderFor("user-patient");
  expect(mockedApi.delta).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: /policy lab/i })).toBeNull();
  expect(screen.getByRole("button", { name: /share an insight/i })).toBeVisible();
  expect(screen.queryByText("Conflict watch")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: /share an insight/i }));
  fireEvent.change(screen.getByLabelText("Note content"), { target: { value: "I felt dizzy this morning." } });
  fireEvent.click(screen.getByRole("button", { name: /save version/i }));
  await waitFor(() => expect(mockedApi.createEntry).toHaveBeenCalledWith(
    "user-patient",
    patient.id,
    expect.objectContaining({ entry_type: "patient_insight", visibility: "patient" }),
  ));

  fireEvent.click(screen.getByRole("button", { name: /capture consult/i }));
  fireEvent.click(screen.getByRole("button", { name: /create review draft/i }));
  await waitFor(() => expect(mockedApi.ingestScribe).toHaveBeenCalledWith(
    "user-patient",
    expect.objectContaining({ interaction_type: "patient_session" }),
  ));
});

test("error boundaries render structured, ordinary, and unknown failures and allow dismissal", async () => {
  localStorage.setItem("continuum-demo-user", "user-clinician");
  mockedApi.me.mockRejectedValueOnce(new ApiError(403, { message: "Clinic scope denied" }));
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Clinic scope denied");
  fireEvent.click(within(screen.getByRole("alert")).getByRole("button"));
  expect(screen.queryByRole("alert")).toBeNull();
});

test("in-workspace async failures are recoverable and use ordinary error messages", async () => {
  await renderFor("user-clinician");
  mockedApi.evidenceReview.mockRejectedValueOnce(new Error("Evidence review unavailable"));
  fireEvent.click(screen.getByRole("button", { name: /^evidence review$/i }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /^review evidence$/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Evidence review unavailable");
  fireEvent.click(within(screen.getByRole("alert")).getByRole("button"));
  fireEvent.click(screen.getAllByRole("button", { name: "Close dialog" })[1]);

  mockedApi.provenance.mockRejectedValueOnce(new Error("Source service unavailable"));
  fireEvent.click(screen.getAllByRole("button", { name: /exact source/i })[0]);
  expect(await screen.findByRole("alert")).toHaveTextContent("Source service unavailable");
  fireEvent.click(within(screen.getByRole("alert")).getByRole("button"));

  mockedApi.feedback.mockRejectedValueOnce("opaque failure");
  fireEvent.click(screen.getByRole("button", { name: "Pin" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
});

test("research, history, admin loading, and retention failures remain visible and recoverable", async () => {
  await renderFor("user-clinician");
  mockedApi.policyEvaluation.mockRejectedValueOnce(new ApiError(409, {}));
  fireEvent.click(screen.getByRole("button", { name: /policy lab/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Request failed with status 409");
  fireEvent.click(within(screen.getByRole("alert")).getByRole("button"));
  fireEvent.click(screen.getByRole("button", { name: /care note/i }));

  mockedApi.versions.mockRejectedValueOnce(new Error("History unavailable"));
  const clinicalCard = screen.getByRole("article", { name: /assessment and plan/i });
  fireEvent.click(within(clinicalCard).getByRole("button", { name: /version 1/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("History unavailable");
  fireEvent.click(screen.getAllByRole("button", { name: "Close dialog" })[1]);

  fireEvent.click(screen.getByRole("button", { name: /dr lina.*clinician/i }));
  fireEvent.click(screen.getByRole("button", { name: /ari admin.*admin/i }));
  await waitFor(() => expect(mockedApi.me).toHaveBeenCalledWith("user-admin"));
  mockedApi.auditVerification.mockRejectedValueOnce(new Error("Audit verifier unavailable"));
  fireEvent.click(await screen.findByRole("button", { name: /trust ops/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Audit verifier unavailable");
  fireEvent.click(within(screen.getByRole("alert")).getByRole("button"));

  mockedApi.auditVerification.mockResolvedValue(verification);
  mockedApi.runRetention.mockRejectedValueOnce(new Error("Retention transaction failed"));
  fireEvent.click(screen.getByRole("button", { name: /run retention policy/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Retention transaction failed");

  fireEvent.click(screen.getByRole("button", { name: /ari admin.*admin/i }));
  fireEvent.click(screen.getByRole("button", { name: /dr lina.*clinician/i }));
  await waitFor(() => expect(mockedApi.me).toHaveBeenCalledWith("user-clinician"));
});

test("identity discovery handles an invalid stored identity, an empty result, and service failure", async () => {
  localStorage.setItem("continuum-demo-user", "invalid-user");
  const fallbackView = render(<App />);
  await waitFor(() => expect(mockedApi.me).toHaveBeenCalledWith("user-clinician"));
  fallbackView.unmount();

  vi.clearAllMocks();
  configureSuccessApi();
  localStorage.setItem("continuum-demo-user", "invalid-user");
  mockedApi.identities.mockResolvedValueOnce({ warning: "none", identities: [] });
  mockedApi.patients.mockResolvedValueOnce({ patients: [] });
  const emptyView = render(<App />);
  await waitFor(() => expect(mockedApi.identities).toHaveBeenCalled());
  emptyView.unmount();

  vi.clearAllMocks();
  configureSuccessApi();
  mockedApi.identities.mockRejectedValueOnce(new Error("Identity service unavailable"));
  const failedView = render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Identity service unavailable");
  failedView.unmount();
});

test("unmounting cancels late identity, viewer, and workspace responses", async () => {
  const identityResult = deferred<{ warning: string; identities: typeof identities }>();
  const viewerResult = deferred<ReturnType<typeof viewer>>();
  mockedApi.identities.mockReturnValueOnce(identityResult.promise);
  mockedApi.me.mockReturnValueOnce(viewerResult.promise);
  const first = render(<App />);
  first.unmount();
  await act(async () => {
    identityResult.resolve({ warning: "late", identities });
    viewerResult.resolve(viewer("clinician"));
    await Promise.resolve();
  });

  vi.clearAllMocks();
  configureSuccessApi();
  const workspaceResult = deferred<typeof workspace>();
  mockedApi.workspace.mockReturnValueOnce(workspaceResult.promise);
  const second = render(<App />);
  await waitFor(() => expect(mockedApi.workspace).toHaveBeenCalled());
  second.unmount();
  await act(async () => {
    workspaceResult.resolve(workspace);
    await Promise.resolve();
  });
});

test("live evidence sync refreshes only on a newer server revision and tolerates poll failures", async () => {
  localStorage.setItem("continuum-demo-user", "user-clinician");
  let poll: (() => Promise<void>) | undefined;
  const interval = vi.spyOn(window, "setInterval").mockImplementation((callback) => {
    poll = callback as () => Promise<void>;
    return 7;
  });
  const clearInterval = vi.spyOn(window, "clearInterval").mockImplementation(() => undefined);
  const view = render(<App />);
  await screen.findByRole("heading", { name: "Maya Chen" });
  expect(screen.getByText("Live evidence sync")).toBeVisible();
  expect(poll).toBeDefined();
  const workspaceCalls = mockedApi.workspace.mock.calls.length;

  mockedApi.glance.mockResolvedValueOnce({ ...glance, source_revision: undefined });
  await act(async () => { await poll?.(); });
  mockedApi.glance.mockResolvedValueOnce(glance);
  await act(async () => { await poll?.(); });
  expect(mockedApi.workspace).toHaveBeenCalledTimes(workspaceCalls);

  mockedApi.glance.mockResolvedValueOnce({ ...glance, source_revision: 2 });
  await act(async () => { await poll?.(); });
  expect(mockedApi.workspace).toHaveBeenCalledTimes(workspaceCalls + 1);
  expect(screen.getByRole("status")).toHaveTextContent("New collaboration evidence synchronized");

  mockedApi.glance.mockRejectedValueOnce(new Error("Transient poll failure"));
  await act(async () => { await poll?.(); });
  expect(screen.queryByRole("alert")).toBeNull();

  view.unmount();
  expect(clearInterval).toHaveBeenCalledWith(7);
  interval.mockRestore();
  clearInterval.mockRestore();
});

test("live evidence sync ignores a response that arrives after unmount", async () => {
  localStorage.setItem("continuum-demo-user", "user-clinician");
  let poll: (() => Promise<void>) | undefined;
  vi.spyOn(window, "setInterval").mockImplementation((callback) => {
    poll = callback as () => Promise<void>;
    return 8;
  });
  const view = render(<App />);
  await screen.findByRole("heading", { name: "Maya Chen" });
  const workspaceCalls = mockedApi.workspace.mock.calls.length;
  const lateGlance = deferred<typeof glance>();
  mockedApi.glance.mockReturnValueOnce(lateGlance.promise);
  const pending = poll?.();
  view.unmount();
  lateGlance.resolve({ ...glance, source_revision: 2 });
  await act(async () => { await pending; });
  expect(mockedApi.workspace).toHaveBeenCalledTimes(workspaceCalls);
  vi.restoreAllMocks();
});

test("toast expiry callback removes status after the configured assurance interval", async () => {
  await renderFor("user-clinician");
  let expiry: (() => void) | undefined;
  const timeout = vi.spyOn(window, "setTimeout").mockImplementation((callback) => {
    expiry = callback as () => void;
    return 1;
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
  });
  expect(mockedApi.feedback).toHaveBeenCalled();
  expect(screen.getByRole("status")).toBeVisible();
  act(() => expiry?.());
  expect(screen.queryByRole("status")).toBeNull();
  timeout.mockRestore();
});
