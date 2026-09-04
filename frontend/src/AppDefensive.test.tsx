import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type {
  DeliveryItem,
  Entry,
  EntryVersion,
  PatientAccessClaim,
  PatientAccessProof,
  RegenerationResult,
  Role,
  StreamingCapture,
  VersionConflictDetail,
} from "./types";

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
  streamRun: null as null | ((interactionType: string) => Promise<StreamingCapture>),
  streamReview: null as null | ((captureId: string, signalId: string, decision: "confirm" | "dismiss") => Promise<StreamingCapture>),
  streamFinalize: null as null | ((captureId: string) => Promise<StreamingCapture>),
  feedback: null as null | ((highlightId: string, action: "accept" | "reject" | "pin") => Promise<void>),
  retention: null as null | (() => Promise<void>),
  deliveryQueue: null as null | ((entry: Entry, contactId: string, purpose: DeliveryItem["communication_purpose"], attestations: { clinical: boolean; identity: boolean; medication: boolean; appointment: boolean }) => Promise<void>),
  deliveryCorrect: null as null | ((original: DeliveryItem, entry: Entry, contactId: string, attestations: { clinical: boolean; identity: boolean; medication: boolean; appointment: boolean }) => Promise<void>),
  deliveryTransition: null as null | ((item: DeliveryItem, outcome: "queued" | "accepted" | "delivered" | "failed") => Promise<void>),
  deliveryAcknowledge: null as null | ((item: DeliveryItem) => Promise<void>),
  deliverySweep: null as null | (() => Promise<void>),
  conflictResolve: null as null | ((decision: "confirm_left" | "confirm_right" | "escalate_unresolved", rationale: string, sourcesReviewed: boolean) => Promise<void>),
  mergeUse: null as null | ((content: string) => void),
  regenerate: null as null | ((transcript: string) => Promise<RegenerationResult>),
  accessIssue: null as null | ((payload: { contactId: string; purpose: PatientAccessClaim["purpose"]; ttlMinutes: number }) => Promise<PatientAccessClaim>),
  accessRedeem: null as null | ((payload: { claimToken: string; recordNumber: string; dateOfBirth: string }) => Promise<PatientAccessProof>),
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
    onRunStreamScenario: NonNullable<typeof captures.streamRun>;
    onReviewStreamSignal: NonNullable<typeof captures.streamReview>;
    onFinalizeStream: NonNullable<typeof captures.streamFinalize>;
    onClose: () => void;
  }) => {
    captures.scribeSubmit = props.onSubmit;
    captures.streamRun = props.onRunStreamScenario;
    captures.streamReview = props.onReviewStreamSignal;
    captures.streamFinalize = props.onFinalizeStream;
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

vi.mock("./components/DeliveryCenter", () => ({
  DeliveryCenter: (props: {
    onQueue: NonNullable<typeof captures.deliveryQueue>;
    onCorrect: NonNullable<typeof captures.deliveryCorrect>;
    onTransition: NonNullable<typeof captures.deliveryTransition>;
    onAcknowledge: NonNullable<typeof captures.deliveryAcknowledge>;
    onSweep: NonNullable<typeof captures.deliverySweep>;
  }) => {
    captures.deliveryQueue = props.onQueue;
    captures.deliveryCorrect = props.onCorrect;
    captures.deliveryTransition = props.onTransition;
    captures.deliveryAcknowledge = props.onAcknowledge;
    captures.deliverySweep = props.onSweep;
    return <div data-testid="delivery-center">Scoped delivery center</div>;
  },
}));

vi.mock("./components/ConflictReviewDialog", () => ({
  ConflictReviewDialog: (props: {
    onResolve: NonNullable<typeof captures.conflictResolve>;
    onClose: () => void;
  }) => {
    captures.conflictResolve = props.onResolve;
    return <button data-testid="close-conflict" onClick={props.onClose}>Close conflict</button>;
  },
}));

vi.mock("./components/ConcurrentEditDialog", () => ({
  ConcurrentEditDialog: (props: {
    onUseDraft: NonNullable<typeof captures.mergeUse>;
    onClose: () => void;
  }) => {
    captures.mergeUse = props.onUseDraft;
    return <button data-testid="close-merge" onClick={props.onClose}>Close merge</button>;
  },
}));

vi.mock("./components/RegenerationDialog", () => ({
  RegenerationDialog: (props: {
    onRegenerate: NonNullable<typeof captures.regenerate>;
    onClose: () => void;
  }) => {
    captures.regenerate = props.onRegenerate;
    return <button data-testid="close-regeneration" onClick={props.onClose}>Close regeneration</button>;
  },
}));

vi.mock("./components/PatientAccessDialog", () => ({
  PatientAccessDialog: (props: {
    onIssue: NonNullable<typeof captures.accessIssue>;
    onRedeem: NonNullable<typeof captures.accessRedeem>;
    onClose: () => void;
  }) => {
    captures.accessIssue = props.onIssue;
    captures.accessRedeem = props.onRedeem;
    return <button data-testid="close-access" onClick={props.onClose}>Close access</button>;
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
    issuePatientAccess: vi.fn(),
    redeemPatientAccess: vi.fn(),
    patientSessionMe: vi.fn(),
    patientSessionWorkspace: vi.fn(),
    queueDelivery: vi.fn(),
    queueCorrection: vi.fn(),
    transitionDelivery: vi.fn(),
    acknowledgeDelivery: vi.fn(),
    escalateDeliveryFollowUps: vi.fn(),
    provenance: vi.fn(),
    feedback: vi.fn(),
    createEntry: vi.fn(),
    editEntry: vi.fn(),
    versions: vi.fn(),
    revert: vi.fn(),
    createThread: vi.fn(),
    ingestScribe: vi.fn(),
    regenerateScribe: vi.fn(),
    startCapture: vi.fn(),
    appendCaptureSegment: vi.fn(),
    reviewSafetySignal: vi.fn(),
    capture: vi.fn(),
    finalizeCapture: vi.fn(),
    resolveConflict: vi.fn(),
    evidenceReview: vi.fn(),
    policyEvaluation: vi.fn(),
    auditVerification: vi.fn(),
    auditEvents: vi.fn(),
    runRetention: vi.fn(),
  },
}));

import App from "./App";
import { ApiError, api } from "./api";
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

const streamCapture: StreamingCapture = {
  id: "capture-1",
  patient_id: patient.id,
  interaction_type: "doctor_consult",
  status: "streaming",
  latest_sequence: 2,
  stream_contract_version: "2026-09-01",
  capabilities: {
    adapter_mode: "provider_neutral_segment_event_contract",
    audio_transcription_active: false,
    clinic_enabled_languages: ["en-SG", "ms-SG"],
    provider_supported_language_bases: ["en", "ms"],
    provider_supported_language_tags: ["en-sg", "ms-sg"],
    unsupported_language_policy: "abstain_and_request_human_transcription",
    speaker_attribution: "adapter_supplied_label_not_biometric_identity",
    quality_policy: "segment_scores_visible_and_fail_closed",
  },
  segments: [],
  safety_signals: [],
  safety_signal_count: 0,
  finalized_entry_id: null,
  provider_status: null,
  provider_failure_code: null,
  started_at: "2026-09-05T10:00:00Z",
  finalized_at: null,
  assurance_boundary: "Synthetic event adapter only.",
};

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(captures, {
    noteSubmit: null,
    commentSubmit: null,
    historyRevert: null,
    scribeSubmit: null,
    streamRun: null,
    streamReview: null,
    streamFinalize: null,
    feedback: null,
    retention: null,
    deliveryQueue: null,
    deliveryCorrect: null,
    deliveryTransition: null,
    deliveryAcknowledge: null,
    deliverySweep: null,
    conflictResolve: null,
    mergeUse: null,
    regenerate: null,
    accessIssue: null,
    accessRedeem: null,
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
  mockedApi.acknowledgeDelivery.mockResolvedValue(deliveryReadiness);
  mockedApi.escalateDeliveryFollowUps.mockResolvedValue(deliveryReadiness);
  mockedApi.issuePatientAccess.mockResolvedValue({
    claim_id: "claim-1",
    patient_id: patient.id,
    channel: "whatsapp",
    masked_destination: "WhatsApp ending 4567",
    purpose: "portal_access",
    status: "issued",
    expires_at: "2026-09-05T10:10:00Z",
    delivery_state: "synthetic_rehearsal_not_sent",
    demo_claim_token: "claim-token",
    security_note: "Synthetic rehearsal only.",
  });
  mockedApi.redeemPatientAccess.mockResolvedValue({
    session_token: "patient-session",
    expires_at: "2026-09-05T10:30:00Z",
    patient_id: patient.id,
    user_id: "user-patient",
    authentication_mode: "channel_claim",
    email_required: false,
  });
  mockedApi.patientSessionMe.mockResolvedValue({
    ...viewer("patient"),
    authentication_mode: "channel_claim",
  });
  mockedApi.patientSessionWorkspace.mockResolvedValue({
    ...workspace,
    viewer: { id: "user-patient", role: "patient" },
    entries: workspace.entries.filter((entry) => entry.visibility === "patient"),
    conflicts: [],
  });
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
  mockedApi.startCapture.mockResolvedValue(streamCapture);
  mockedApi.appendCaptureSegment.mockResolvedValue(streamCapture);
  mockedApi.reviewSafetySignal.mockResolvedValue({} as never);
  mockedApi.capture.mockResolvedValue(streamCapture);
  mockedApi.finalizeCapture.mockResolvedValue({ ...streamCapture, status: "finalized" });
  mockedApi.resolveConflict.mockResolvedValue(workspace.conflicts[0]);
  mockedApi.regenerateScribe.mockResolvedValue({
    entry_id: "entry-regenerated",
    predecessor_entry_id: "entry-ai",
    status: "new_ai_proposal_created",
    provider: "local",
    provider_status: "live",
    provider_failure_code: null,
    flags: ["human_review_required"],
    preservation_receipt: {
      unchanged: true,
      protected_state_hash: "a".repeat(64),
      protected_highlight_count: 1,
      completed_task_count: 0,
      resolved_conflict_count: 0,
      released_delivery_count: 0,
      reviewed_signal_count: 0,
      meaning: "Protected state unchanged.",
    },
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
  await expect(captures.streamRun?.("doctor_consult")).rejects.toThrow(
    "No active patient capture context.",
  );

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

test("advanced stale callbacks re-check live identity, role, patient, and conflict state", async () => {
  render(<App />);
  await screen.findByRole("heading", { name: "Maya Chen" });
  expect(captures.deliveryQueue).not.toBeNull();

  fireEvent.click(screen.getByRole("button", { name: /capture consult/i }));
  fireEvent.click(screen.getByTestId("close-scribe"));
  fireEvent.click(screen.getByRole("button", { name: /compare both sources/i }));
  fireEvent.click(screen.getByTestId("close-conflict"));
  const aiCard = screen.getByRole("article", { name: /ai consult draft/i });
  const clinicalCard = screen.getByRole("article", { name: /assessment and plan/i });
  fireEvent.click(screen.getByRole("button", { name: /phone-only access/i }));
  fireEvent.click(screen.getByTestId("close-access"));
  fireEvent.click(within(aiCard).getByRole("button", { name: /regenerate proposal/i }));
  fireEvent.click(screen.getByTestId("close-regeneration"));

  const conflictDetail: VersionConflictDetail = {
    code: "version_conflict",
    message: "Concurrent update",
    expected_version: 1,
    current_version: 2,
    current_version_id: "current-2",
    base_snapshot: null,
    current_snapshot: null,
    proposed_content: "Stale proposal",
    proposed_content_hash: "a".repeat(64),
    merge_assistance: null,
    resolution: "Current source is unavailable; fail closed.",
  };
  mockedApi.editEntry.mockRejectedValueOnce(new ApiError(409, conflictDetail));
  fireEvent.click(within(clinicalCard).getByRole("button", { name: /edit section/i }));
  await act(async () => captures.noteSubmit?.({
    title: "AI consult draft",
    content: "Stale proposal",
    entryType: "ai_doctor_consult_summary",
    visibility: "internal",
  }));
  await waitFor(() => expect(captures.mergeUse).not.toBeNull());
  act(() => captures.mergeUse?.("Must not open"));
  fireEvent.click(screen.getByTestId("close-merge"));
  act(() => captures.mergeUse?.("Still must not open"));

  fireEvent.click(screen.getByRole("button", { name: /dr lina.*clinician/i }));
  fireEvent.click(screen.getByRole("button", { name: /empty clinician.*clinician/i }));
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Maya Chen" })).toBeNull());

  const deliveryItem: DeliveryItem = {
    id: "delivery-1",
    patient_id: patient.id,
    source_entry_id: workspace.entries[3].id,
    source_version_id: workspace.entries[3].version.id,
    source_is_current: true,
    correction_for_id: null,
    channel: "whatsapp",
    masked_destination: "WhatsApp ending 4567",
    content_snapshot: "Synthetic copy",
    content_hash: "b".repeat(64),
    status: "queued",
    receipt_meaning: "Queued only",
    communication_purpose: "care_summary",
    follow_up: null,
    attempt_count: 0,
    created_at: "2026-09-05T10:00:00Z",
    accepted_at: null,
    delivered_at: null,
    superseded_at: null,
  };
  const attestations = { clinical: true, identity: true, medication: true, appointment: false };
  const writeCounts = {
    queue: mockedApi.queueDelivery.mock.calls.length,
    correction: mockedApi.queueCorrection.mock.calls.length,
    transition: mockedApi.transitionDelivery.mock.calls.length,
    acknowledge: mockedApi.acknowledgeDelivery.mock.calls.length,
    sweep: mockedApi.escalateDeliveryFollowUps.mock.calls.length,
    conflict: mockedApi.resolveConflict.mock.calls.length,
  };
  await act(async () => {
    await captures.deliveryQueue?.(workspace.entries[3], "contact-whatsapp", "care_summary", attestations);
    await captures.deliveryCorrect?.(deliveryItem, workspace.entries[3], "contact-whatsapp", attestations);
    await captures.deliveryTransition?.(deliveryItem, "accepted");
    await captures.deliveryAcknowledge?.(deliveryItem);
    await captures.deliverySweep?.();
    await captures.conflictResolve?.("confirm_left", "stale decision", true);
    await expect(captures.streamRun?.("doctor_consult")).rejects.toThrow(
      "No active patient capture context.",
    );
    await expect(captures.regenerate?.("stale transcript")).rejects.toThrow(
      "No AI proposal is selected for regeneration.",
    );
    await expect(captures.accessIssue?.({
      contactId: "contact-whatsapp",
      purpose: "portal_access",
      ttlMinutes: 10,
    })).rejects.toThrow("Only an authorized care-team member can issue patient access.");
    await expect(captures.accessRedeem?.({
      claimToken: "stale",
      recordNumber: patient.synthetic_record_number,
      dateOfBirth: patient.date_of_birth,
    })).rejects.toThrow("No active patient access context.");
    await captures.streamReview?.("capture-1", "signal-1", "confirm");
    await captures.streamReview?.("capture-1", "signal-1", "dismiss");
    await captures.streamFinalize?.("capture-1");
  });
  expect(mockedApi.queueDelivery).toHaveBeenCalledTimes(writeCounts.queue);
  expect(mockedApi.queueCorrection).toHaveBeenCalledTimes(writeCounts.correction);
  expect(mockedApi.transitionDelivery).toHaveBeenCalledTimes(writeCounts.transition);
  expect(mockedApi.acknowledgeDelivery).toHaveBeenCalledTimes(writeCounts.acknowledge);
  expect(mockedApi.escalateDeliveryFollowUps).toHaveBeenCalledTimes(writeCounts.sweep);
  expect(mockedApi.resolveConflict).toHaveBeenCalledTimes(writeCounts.conflict);
  expect(mockedApi.reviewSafetySignal).toHaveBeenNthCalledWith(
    1,
    "user-empty",
    "signal-1",
    "confirm",
    "Confirmed directly with the patient during the consult.",
  );
  expect(mockedApi.reviewSafetySignal).toHaveBeenNthCalledWith(
    2,
    "user-empty",
    "signal-1",
    "dismiss",
    "Dismissed after clinician review of the source interaction.",
  );

  mockedApi.patients.mockResolvedValueOnce({ patients: [] });
  fireEvent.click(screen.getByRole("button", { name: /empty clinician.*clinician/i }));
  fireEvent.click(screen.getByRole("button", { name: /ari admin.*admin/i }));
  await waitFor(() => expect(mockedApi.me).toHaveBeenCalledWith("user-admin"));
  await captures.deliveryTransition?.(deliveryItem, "accepted");
  expect(mockedApi.transitionDelivery).toHaveBeenCalledTimes(writeCounts.transition);

  fireEvent.click(screen.getByRole("button", { name: /ari admin.*admin/i }));
  fireEvent.click(screen.getByRole("button", { name: /maya chen.*patient/i }));
  await screen.findByRole("heading", { name: "Maya Chen" });
  await expect(captures.accessIssue?.({
    contactId: "contact-whatsapp",
    purpose: "portal_access",
    ttlMinutes: 10,
  })).rejects.toThrow("Only an authorized care-team member can issue patient access.");
  mockedApi.patientSessionWorkspace.mockResolvedValueOnce(workspace);
  await expect(captures.accessRedeem?.({
    claimToken: "claim-token",
    recordNumber: patient.synthetic_record_number,
    dateOfBirth: patient.date_of_birth,
  })).rejects.toThrow("returned scope was not patient-only");
});
