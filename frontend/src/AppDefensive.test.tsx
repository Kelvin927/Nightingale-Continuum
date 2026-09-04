import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { Entry, EntryVersion, Role } from "./types";

const captures = vi.hoisted(() => ({
  noteSubmit: null as null | ((payload: {
    title: string;
    content: string;
    entryType: string;
    visibility: string;
  }) => Promise<void>),
  commentSubmit: null as null | ((title: string, body: string, assignedTo: string | null) => Promise<void>),
  historyRevert: null as null | ((targetVersion: number) => Promise<void>),
  scribeSubmit: null as null | ((interactionType: string, transcript: string) => Promise<{
    receipt: Record<string, number>;
    flags: string[];
  }>),
  feedback: null as null | ((highlightId: string, action: "accept" | "reject" | "pin") => Promise<void>),
  retention: null as null | (() => Promise<void>),
}));

vi.mock("./components/Dialogs", () => ({
  NoteDialog: (props: {
    onSubmit: NonNullable<typeof captures.noteSubmit>;
    onClose: () => void;
  }) => {
    captures.noteSubmit = props.onSubmit;
    return <button data-testid="close-note" onClick={props.onClose}>Close note</button>;
  },
  CommentDialog: (props: {
    onSubmit: NonNullable<typeof captures.commentSubmit>;
    onClose: () => void;
  }) => {
    captures.commentSubmit = props.onSubmit;
    return <button data-testid="close-comment" onClick={props.onClose}>Close comment</button>;
  },
  HistoryDialog: (props: {
    entry: Entry;
    versions: EntryVersion[];
    loading: boolean;
    onRevert: NonNullable<typeof captures.historyRevert>;
    onClose: () => void;
  }) => {
    captures.historyRevert = props.onRevert;
    return <button data-testid="close-history" onClick={props.onClose}>Close history</button>;
  },
  ScribeDialog: (props: {
    onSubmit: NonNullable<typeof captures.scribeSubmit>;
    onClose: () => void;
  }) => {
    captures.scribeSubmit = props.onSubmit;
    return <button data-testid="close-scribe" onClick={props.onClose}>Close scribe</button>;
  },
}));

vi.mock("./components/GlanceBoard", () => ({
  GlanceBoard: (props: {
    onFeedback: NonNullable<typeof captures.feedback>;
  }) => {
    captures.feedback = props.onFeedback;
    return <div data-testid="glance-projection">Scoped glance</div>;
  },
}));

vi.mock("./components/AdminPanel", () => ({
  AdminPanel: (props: { onRetention: NonNullable<typeof captures.retention> }) => {
    captures.retention = props.onRetention;
    return <div data-testid="admin-panel">Scoped admin panel</div>;
  },
}));

vi.mock("./api", () => ({
  ApiError: class MockApiError extends Error {
    detail: unknown;
    status: number;

    constructor(status: number, detail: unknown) {
      super(`Request failed with status ${status}`);
      this.status = status;
      this.detail = detail;
    }
  },
  api: {
    identities: vi.fn(),
    me: vi.fn(),
    patients: vi.fn(),
    workspace: vi.fn(),
    glance: vi.fn(),
    delta: vi.fn(),
    deliveryReadiness: vi.fn(),
    queueDelivery: vi.fn(),
    queueCorrection: vi.fn(),
    transitionDelivery: vi.fn(),
    provenance: vi.fn(),
    feedback: vi.fn(),
    createEntry: vi.fn(),
    editEntry: vi.fn(),
    versions: vi.fn(),
    revert: vi.fn(),
    createThread: vi.fn(),
    ingestScribe: vi.fn(),
    regenerateScribe: vi.fn(),
    evidenceReview: vi.fn(),
    policyEvaluation: vi.fn(),
    auditVerification: vi.fn(),
    auditEvents: vi.fn(),
    runRetention: vi.fn(),
  },
}));

import App from "./App";
import { api } from "./api";
import {
  delta,
  deliveryReadiness,
  glance,
  identities,
  patient,
  provenance,
  versionOne,
  viewer,
  workspace,
} from "./test/fixtures";

const mockedApi = vi.mocked(api);
const emptyIdentity = {
  id: "user-empty",
  display_name: "Empty Clinician",
  role: "clinician" as Role,
};

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(captures, {
    noteSubmit: null,
    commentSubmit: null,
    historyRevert: null,
    scribeSubmit: null,
    feedback: null,
    retention: null,
  });
  localStorage.setItem("continuum-demo-user", "user-clinician");
  mockedApi.identities.mockResolvedValue({
    warning: "Synthetic identities",
    identities: [...identities, emptyIdentity],
  });
  mockedApi.me.mockImplementation(async (userId) => {
    if (userId === emptyIdentity.id) return { ...viewer("clinician"), ...emptyIdentity };
    const role = identities.find((identity) => identity.id === userId)?.role ?? "clinician";
    return viewer(role);
  });
  mockedApi.patients.mockImplementation(async (userId) => ({
    patients: userId === emptyIdentity.id ? [] : [patient],
  }));
  mockedApi.workspace.mockResolvedValue(workspace);
  mockedApi.glance.mockResolvedValue(glance);
  mockedApi.delta.mockResolvedValue(delta);
  mockedApi.deliveryReadiness.mockResolvedValue(deliveryReadiness);
  mockedApi.queueDelivery.mockResolvedValue(deliveryReadiness);
  mockedApi.queueCorrection.mockResolvedValue(deliveryReadiness);
  mockedApi.transitionDelivery.mockResolvedValue(deliveryReadiness);
  mockedApi.provenance.mockResolvedValue(provenance);
  mockedApi.feedback.mockResolvedValue({
    status: "rejected",
    adaptive_score: 0,
    shadow_adaptive_score: -0.1,
    rank_score: 8,
    ranking_mode: "fixed_safety_with_shadow_learning",
  });
  mockedApi.versions.mockResolvedValue({
    entry_id: "entry-clinician",
    current_version: 1,
    versions: [versionOne],
  });
  mockedApi.createEntry.mockResolvedValue({});
  mockedApi.editEntry.mockResolvedValue({});
  mockedApi.revert.mockResolvedValue({});
  mockedApi.createThread.mockResolvedValue({});
  mockedApi.ingestScribe.mockResolvedValue({
    entry_id: "entry-1",
    status: "proposed",
    provider: "local",
    provider_status: "live",
    provider_failure_code: null,
    redaction_receipt: {
      detector_version: "v1",
      entity_counts: {},
      clinical_anchor_count: 0,
      clinical_anchors_preserved: true,
      passed: true,
    },
    flags: [],
  });
  mockedApi.evidenceReview.mockResolvedValue({
    intent: "overview",
    answer_state: "insufficient_evidence",
    summary: "No source-bound signal matched this question.",
    claims: [],
    open_actions: [],
    conflicts: [],
    abstention_reason: "The authorized record does not support a sourced answer.",
    provider: "local-evidence-reviewer-v1",
    safety_notice: "Decision support only.",
  });
  mockedApi.auditVerification.mockResolvedValue({
    valid: true,
    events_checked: 1,
    first_invalid_sequence: null,
    reason: null,
  });
  mockedApi.auditEvents.mockResolvedValue({ events: [] });
  mockedApi.runRetention.mockResolvedValue({ evaluated_at: "2026-08-26T12:00:00Z", changes: [] });
});

test("stale dialog callbacks fail closed after identity scope is cleared", async () => {
  render(<App />);
  await screen.findByRole("heading", { name: "Maya Chen" });
  expect(screen.getByTestId("glance-projection")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: /add note/i }));
  fireEvent.click(screen.getByTestId("close-note"));

  fireEvent.click(screen.getAllByRole("button", { name: "Comment" })[0]);
  fireEvent.click(screen.getByTestId("close-comment"));

  fireEvent.click(screen.getAllByRole("button", { name: /version 1/i })[0]);
  await waitFor(() => expect(captures.historyRevert).not.toBeNull());
  fireEvent.click(screen.getByTestId("close-history"));

  fireEvent.click(screen.getByRole("button", { name: /capture consult/i }));
  fireEvent.click(screen.getByTestId("close-scribe"));

  fireEvent.click(screen.getByRole("button", { name: /dr lina.*clinician/i }));
  fireEvent.click(screen.getByRole("button", { name: /empty clinician.*clinician/i }));
  await waitFor(() => expect(mockedApi.patients).toHaveBeenCalledWith("user-empty"));
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Maya Chen" })).toBeNull());
  expect(screen.queryByTestId("glance-projection")).toBeNull();

  const workspaceCalls = mockedApi.workspace.mock.calls.length;
  const glanceCalls = mockedApi.glance.mock.calls.length;
  await act(async () => {
    await captures.noteSubmit?.({
      title: "Stale",
      content: "Stale",
      entryType: "clinician_note",
      visibility: "internal",
    });
    await captures.commentSubmit?.("Stale", "Stale", null);
    await captures.historyRevert?.(1);
    expect(await captures.scribeSubmit?.("doctor_consult", "Stale")).toEqual({
      receipt: {},
      flags: [],
      clinicalAnchorCount: 0,
      clinicalAnchorsPreserved: false,
      providerStatus: "failed_closed",
      providerFailureCode: "inactive_capture_context",
    });
    await captures.feedback?.("highlight-1", "reject");
  });

  expect(mockedApi.createEntry).not.toHaveBeenCalled();
  expect(mockedApi.createThread).not.toHaveBeenCalled();
  expect(mockedApi.revert).not.toHaveBeenCalled();
  expect(mockedApi.ingestScribe).not.toHaveBeenCalled();
  expect(mockedApi.feedback).not.toHaveBeenCalled();
  expect(mockedApi.workspace).toHaveBeenCalledTimes(workspaceCalls);
  expect(mockedApi.glance).toHaveBeenCalledTimes(glanceCalls);

  fireEvent.click(screen.getByRole("button", { name: /empty clinician.*clinician/i }));
  fireEvent.click(screen.getByRole("button", { name: /ari admin.*admin/i }));
  await waitFor(() => expect(mockedApi.me).toHaveBeenCalledWith("user-admin"));
  fireEvent.click(await screen.findByRole("button", { name: /trust ops/i }));
  await waitFor(() => expect(captures.retention).not.toBeNull());
  fireEvent.click(screen.getByRole("button", { name: /ari admin.*admin/i }));
  fireEvent.click(screen.getByRole("button", { name: /dr lina.*clinician/i }));
  await waitFor(() => expect(mockedApi.me).toHaveBeenCalledWith("user-clinician"));
  await act(async () => captures.retention?.());
  expect(mockedApi.runRetention).not.toHaveBeenCalled();
});
