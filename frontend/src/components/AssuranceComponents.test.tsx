import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import {
  aiEntry,
  auditEvents,
  clinicianEntry,
  delta,
  evidenceReview,
  evaluation,
  patientEntry,
  provenance,
  verification,
  versionOne,
  versionTwo,
} from "../test/fixtures";
import type { StreamingCapture } from "../types";
import { AdminPanel } from "./AdminPanel";
import { DeltaLens } from "./DeltaLens";
import { CommentDialog, HistoryDialog, NoteDialog, ScribeDialog } from "./Dialogs";
import { ProvenanceDrawer } from "./ProvenanceDrawer";
import { ResearchPanel } from "./ResearchPanel";
import { ReviewCopilotDialog } from "./ReviewCopilot";
import { Timeline } from "./Timeline";

test("evidence review copilot keeps answers source-bound and exposes workflow links", async () => {
  const onAsk = vi.fn().mockResolvedValue(undefined);
  const onSource = vi.fn();
  const onTaskSource = vi.fn();
  const onClose = vi.fn();
  const { rerender } = render(
    <ReviewCopilotDialog
      result={null}
      busy={false}
      onClose={onClose}
      onAsk={onAsk}
      onSource={onSource}
      onTaskSource={onTaskSource}
    />,
  );
  fireEvent.change(screen.getByLabelText("Ask about this longitudinal record"), {
    target: { value: "No" },
  });
  expect(screen.getByRole("button", { name: /^review evidence$/i })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Which medication evidence conflicts?" }));
  fireEvent.submit(screen.getByRole("button", { name: /^review evidence$/i }).closest("form")!);
  await waitFor(() => expect(onAsk).toHaveBeenCalledWith("Which medication evidence conflicts?"));

  rerender(
    <ReviewCopilotDialog
      result={evidenceReview}
      busy={false}
      onClose={onClose}
      onAsk={onAsk}
      onSource={onSource}
      onTaskSource={onTaskSource}
    />,
  );
  expect(screen.getByText(evidenceReview.summary)).toBeVisible();
  expect(screen.getByText(evidenceReview.claims[0].quote)).toBeVisible();
  expect(screen.getByText("Explicit owner assigned")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /verify exact source/i }));
  fireEvent.click(screen.getByRole("button", { name: /open source entry/i }));
  expect(onSource).toHaveBeenCalledWith("span-1");
  expect(onTaskSource).toHaveBeenCalledWith("entry-clinician");
  screen.getAllByRole("button", { name: "Close dialog" }).forEach(fireEvent.click);
  expect(onClose).toHaveBeenCalledTimes(2);
});

test("evidence review copilot communicates abstention, unowned work, and loading", () => {
  const result = {
    ...evidenceReview,
    answer_state: "workflow_only" as const,
    claims: [],
    conflicts: [],
    abstention_reason: "The record has workflow items but no matching sourced clinical signal.",
    open_actions: [
      {
        ...evidenceReview.open_actions[0],
        assigned_to: null,
        due_at: null,
        source_entry_id: null,
      },
    ],
  };
  const { rerender } = render(
    <ReviewCopilotDialog
      result={result}
      busy
      onClose={vi.fn()}
      onAsk={vi.fn()}
      onSource={vi.fn()}
      onTaskSource={vi.fn()}
    />,
  );
  expect(screen.getByText(result.abstention_reason)).toBeVisible();
  expect(screen.getByText("Owner required")).toBeVisible();
  expect(screen.queryByRole("button", { name: /open source entry/i })).toBeNull();
  expect(screen.getByRole("button", { name: "Reviewing..." })).toBeDisabled();

  rerender(
    <ReviewCopilotDialog
      result={{ ...result, answer_state: "insufficient_evidence", open_actions: [] }}
      busy={false}
      onClose={vi.fn()}
      onAsk={vi.fn()}
      onSource={vi.fn()}
      onTaskSource={vi.fn()}
    />,
  );
  expect(screen.queryByText("Open workflow")).toBeNull();
});

test("admin panel renders valid and review states, audit rows, and retention action", () => {
  const onRetention = vi.fn();
  const { rerender } = render(
    <AdminPanel
      verification={verification}
      events={auditEvents}
      retentionBusy={false}
      onRetention={onRetention}
    />,
  );
  expect(screen.getByText("Audit chain verified")).toBeVisible();
  expect(screen.getByText("42 metadata-only events checked")).toBeVisible();
  expect(screen.getByText("clinician")).toBeVisible();
  expect(screen.getByText("system")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /run retention policy/i }));
  expect(onRetention).toHaveBeenCalledOnce();

  rerender(
    <AdminPanel verification={null} events={[]} retentionBusy onRetention={onRetention} />,
  );
  expect(screen.getByText("Audit chain needs review")).toBeVisible();
  expect(screen.getByRole("button", { name: /evaluating/i })).toBeDisabled();
});

test("delta lens links exact evidence and tolerates absent comparison and evidence", () => {
  const onSource = vi.fn();
  const { rerender } = render(<DeltaLens delta={delta} onSource={onSource} />);
  expect(screen.getByText("24 Aug")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Open source for Renal result" }));
  expect(onSource).toHaveBeenCalledWith("span-2");
  expect(screen.queryByRole("button", { name: "Open source for Medication dose" })).toBeNull();

  rerender(<DeltaLens delta={{ ...delta, comparison: null, new: [] }} onSource={onSource} />);
  expect(screen.queryByText("24 Aug")).toBeNull();
});

test("provenance drawer exposes the complete receipt and both close affordances", () => {
  const onClose = vi.fn();
  const { rerender } = render(<ProvenanceDrawer source={provenance} onClose={onClose} />);
  expect(screen.getByText(provenance.quote)).toBeVisible();
  expect(screen.getByText(/character span/i).nextSibling).toHaveTextContent("0-41");
  expect(screen.getByText(provenance.content_hash)).toBeVisible();
  screen.getAllByRole("button", { name: /close source drawer/i }).forEach(fireEvent.click);
  expect(onClose).toHaveBeenCalledTimes(2);

  rerender(
    <ProvenanceDrawer
      source={{
        ...provenance,
        source_is_current: false,
        current_version_id: "version-2",
        current_version: 2,
        current_content: versionTwo.content,
        current_content_hash: versionTwo.content_hash,
        changes_since_source: [
          { operation: "replace", before: versionOne.content, after: versionTwo.content },
        ],
      }}
      onClose={onClose}
    />,
  );
  expect(screen.getByText(/Source updated after this evidence was anchored/i)).toBeVisible();
  expect(screen.getByText("Anchored v1")).toBeVisible();
  expect(screen.getByText("Current v2")).toBeVisible();
  expect(screen.getByText(versionTwo.content)).toBeVisible();
});

test("research panel distinguishes loading, evaluable, and unsafe evidence", () => {
  const { rerender } = render(<ResearchPanel evaluation={null} />);
  expect(screen.getByText("Not estimated")).toBeVisible();
  expect(screen.getByText("Loading")).toBeVisible();

  rerender(<ResearchPanel evaluation={evaluation} />);
  expect(screen.getByText("72.0%")).toBeVisible();
  expect(screen.getByText("41.2")).toBeVisible();
  expect(screen.queryByText("Do not promote this policy.")).toBeNull();
  expect(screen.getByText("Consistency")).toBeVisible();

  rerender(
    <ResearchPanel
      evaluation={{
        ...evaluation,
        doubly_robust_value: null,
        overlap_warning: true,
        status: "insufficient_data",
      }}
    />,
  );
  expect(screen.getByText("Not estimated")).toBeVisible();
  expect(screen.getByText("Do not promote this policy.")).toBeVisible();
});

test("timeline covers source highlighting, permissions, threads, labels, and every filter", () => {
  const handlers = {
    onHistory: vi.fn(),
    onEdit: vi.fn(),
    onComment: vi.fn(),
    onRegenerate: vi.fn(),
  };
  const unknownEntry = {
    ...clinicianEntry,
    id: "entry-unknown",
    entry_type: "custom_event",
    title: "Custom event",
    author: null,
    source_uri: null,
    comment_threads: [
      ...(clinicianEntry.comment_threads ?? []),
      {
        ...(clinicianEntry.comment_threads ?? [])[0],
        id: "thread-2",
        title: "Second thread",
        resolved: true,
      },
    ],
  };
  const { rerender } = render(
    <Timeline
      entries={[clinicianEntry, aiEntry, patientEntry, unknownEntry]}
      role="clinician"
      activeSource={provenance}
      {...handlers}
    />,
  );
  expect(screen.getByText(provenance.quote).tagName).toBe("MARK");
  expect(screen.getByText("custom event")).toBeVisible();
  expect(screen.getAllByText("System")).toHaveLength(2);
  expect(screen.getByText("cold tier")).toBeVisible();

  const clinicalCard = screen.getByRole("article", { name: /assessment and plan/i });
  fireEvent.click(within(clinicalCard).getByRole("button", { name: /version 1/i }));
  fireEvent.click(within(clinicalCard).getByRole("button", { name: /edit section/i }));
  fireEvent.click(within(clinicalCard).getByRole("button", { name: /1 thread/i }));
  expect(within(clinicalCard).getByText("I will verify this today.")).toBeVisible();
  fireEvent.click(within(clinicalCard).getByRole("button", { name: /start another thread/i }));
  expect(handlers.onHistory).toHaveBeenCalledWith(clinicianEntry);
  expect(handlers.onEdit).toHaveBeenCalledWith(clinicianEntry);
  expect(handlers.onComment).toHaveBeenCalledWith(clinicianEntry);
  const customCard = screen.getByRole("article", { name: /custom event/i });
  fireEvent.click(within(customCard).getByRole("button", { name: /2 threads/i }));
  expect(within(customCard).getByText("Resolved")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "AI drafts" }));
  expect(screen.getByText("AI consult draft")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /regenerate proposal/i }));
  expect(handlers.onRegenerate).toHaveBeenCalledWith(aiEntry);
  expect(screen.queryByText("Assessment and plan")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Patient" }));
  expect(screen.getByText("What matters to me")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Human" }));
  expect(screen.queryByText("AI consult draft")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "All" }));

  rerender(
    <Timeline entries={[]} role="patient" activeSource={null} {...handlers} />,
  );
  expect(screen.getByText("No entries match this filter.")).toBeVisible();
});

test("timeline handles mismatched source text, no-thread comments, and patient permissions", () => {
  const onComment = vi.fn();
  const { rerender } = render(
    <Timeline
      entries={[patientEntry]}
      role="patient"
      activeSource={{ ...provenance, source_entry_id: patientEntry.id, quote: "not present" }}
      onHistory={vi.fn()}
      onEdit={vi.fn()}
      onComment={onComment}
      onRegenerate={vi.fn()}
    />,
  );
  expect(screen.queryByRole("button", { name: /comment/i })).toBeNull();
  expect(screen.getByRole("button", { name: /edit section/i })).toBeVisible();

  rerender(
    <Timeline
      entries={[{ ...clinicianEntry, comment_threads: [] }]}
      role="staff"
      activeSource={null}
      onHistory={vi.fn()}
      onEdit={vi.fn()}
      onComment={onComment}
      onRegenerate={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Comment" }));
  expect(onComment).toHaveBeenCalled();
});

test("note dialog creates patient-facing notes, edits entries, and reports both error forms", async () => {
  const onClose = vi.fn();
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  const { unmount } = render(
    <NoteDialog role="clinician" editing={null} onClose={onClose} onSubmit={onSubmit} />,
  );
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Confirmed care summary" } });
  fireEvent.change(screen.getByLabelText("Note content"), { target: { value: "Confirmed summary" } });
  fireEvent.click(screen.getByLabelText(/patient-facing summary/i));
  fireEvent.submit(screen.getByRole("button", { name: /save version/i }).closest("form")!);
  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
    title: "Confirmed care summary",
    content: "Confirmed summary",
    entryType: "patient_summary",
    visibility: "patient",
  }));
  expect(onClose).toHaveBeenCalled();
  unmount();

  const failure = vi.fn().mockRejectedValueOnce(new Error("Version conflict"));
  const editingView = render(
    <NoteDialog role="clinician" editing={clinicianEntry} onClose={vi.fn()} onSubmit={failure} />,
  );
  fireEvent.submit(screen.getByRole("button", { name: /save version/i }).closest("form")!);
  expect(await screen.findByText("Version conflict")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  editingView.unmount();

  render(
    <NoteDialog role="staff" editing={null} onClose={vi.fn()} onSubmit={vi.fn().mockRejectedValue("failure")} />,
  );
  fireEvent.change(screen.getByLabelText("Note content"), { target: { value: "Workflow" } });
  fireEvent.submit(screen.getByRole("button", { name: /save version/i }).closest("form")!);
  expect(await screen.findByText("Could not save the note.")).toBeVisible();
});

test("comment dialog submits assigned and unassigned review threads", async () => {
  const assignedSubmit = vi.fn().mockResolvedValue(undefined);
  const first = render(
    <CommentDialog
      entry={clinicianEntry}
      collaborator={{ id: "user-staff", name: "Nurse Noor" }}
      onClose={vi.fn()}
      onSubmit={assignedSubmit}
    />,
  );
  fireEvent.change(screen.getByLabelText("Thread title"), { target: { value: "Dose review" } });
  fireEvent.change(screen.getByLabelText("Comment"), { target: { value: "Please reconcile" } });
  fireEvent.click(screen.getByLabelText(/assign to nurse noor/i));
  fireEvent.submit(screen.getByRole("button", { name: /post thread/i }).closest("form")!);
  await waitFor(() => expect(assignedSubmit).toHaveBeenCalledWith("Dose review", "Please reconcile", "user-staff"));
  first.unmount();

  const unassignedSubmit = vi.fn().mockResolvedValue(undefined);
  render(
    <CommentDialog
      entry={clinicianEntry}
      collaborator={null}
      onClose={vi.fn()}
      onSubmit={unassignedSubmit}
    />,
  );
  fireEvent.change(screen.getByLabelText("Comment"), { target: { value: "General review" } });
  fireEvent.submit(screen.getByRole("button", { name: /post thread/i }).closest("form")!);
  await waitFor(() => expect(unassignedSubmit).toHaveBeenCalledWith("Review this entry", "General review", null));
});

test("history dialog covers loading, current version, and append-only restoration", async () => {
  const onClose = vi.fn();
  const onRevert = vi.fn().mockResolvedValue(undefined);
  const { rerender } = render(
    <HistoryDialog
      entry={{ ...clinicianEntry, current_version: 2 }}
      versions={[]}
      loading
      onClose={onClose}
      onRevert={onRevert}
    />,
  );
  expect(screen.getByText("Loading versions...")).toBeVisible();
  rerender(
    <HistoryDialog
      entry={{ ...clinicianEntry, current_version: 2 }}
      versions={[versionOne, versionTwo]}
      loading={false}
      onClose={onClose}
      onRevert={onRevert}
    />,
  );
  expect(screen.getByText("Current")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /restore/i }));
  await waitFor(() => expect(onRevert).toHaveBeenCalledWith(1));
  expect(onClose).toHaveBeenCalled();
});

class FakeMediaRecorder {
  start = vi.fn();
  stop = vi.fn();
}

test("scribe dialog covers capture success, stop, redaction receipt, and cleanup", async () => {
  const stop = vi.fn();
  const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] });
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  const onSubmit = vi.fn().mockResolvedValue({ receipt: { PERSON: 1 }, flags: ["prompt_injection_pattern"] });
  const onClose = vi.fn();
  const view = render(<ScribeDialog role="clinician" onClose={onClose} onSubmit={onSubmit} />);

  fireEvent.change(screen.getByLabelText("Synthetic transcript"), {
    target: { value: "Maya Chen reports a 20 mg dose and pending lab." },
  });

  fireEvent.click(screen.getByRole("button", { name: /start local capture/i }));
  expect(await screen.findByText("Recording locally")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /stop capture/i }));
  expect(screen.getByText("Ready")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /create review draft/i }));
  expect(await screen.findByText("Draft submitted for human review")).toBeVisible();
  expect(onSubmit).toHaveBeenCalledWith("doctor_consult", "Maya Chen reports a 20 mg dose and pending lab.");
  expect(screen.getByText("prompt injection pattern")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /return to care note/i }));
  expect(onClose).toHaveBeenCalled();
  view.unmount();
  expect(stop).toHaveBeenCalled();
  vi.unstubAllGlobals();
});

test.each([
  ["patient", "patient_session"],
  ["staff", "nurse_consult"],
] as const)("scribe falls back without microphone for %s interactions", async (role, expectedType) => {
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia: vi.fn().mockRejectedValue(new Error("denied")) },
    configurable: true,
  });
  const onSubmit = vi.fn().mockResolvedValue({ receipt: {}, flags: [] });
  render(<ScribeDialog role={role} onClose={vi.fn()} onSubmit={onSubmit} />);
  fireEvent.click(screen.getByRole("button", { name: /start local capture/i }));
  await waitFor(() => expect(screen.getByText("Ready")).toBeVisible());
  fireEvent.click(screen.getByRole("button", { name: /create review draft/i }));
  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expectedType, expect.any(String)));
});

const streamingCapture: StreamingCapture = {
  id: "capture-stream-1",
  patient_id: "patient-1",
  interaction_type: "doctor_consult",
  status: "streaming",
  latest_sequence: 2,
  stream_contract_version: "2026-09-01",
  capabilities: {
    adapter_mode: "provider_neutral_segment_event_contract",
    audio_transcription_active: false,
    clinic_enabled_languages: ["en-SG", "ms-SG", "zh-SG"],
    provider_supported_language_bases: ["en", "ms", "zh"],
    provider_supported_language_tags: ["en", "en-sg", "ms", "ms-sg", "zh", "zh-sg"],
    unsupported_language_policy: "abstain_and_request_human_transcription",
    speaker_attribution: "adapter_supplied_label_not_biometric_identity",
    quality_policy: "segment_scores_visible_and_fail_closed",
  },
  segments: [
    {
      id: "segment-1",
      sequence: 1,
      chunk_id: "chunk-1",
      start_ms: 0,
      end_ms: 2_000,
      speaker_label: "clinician",
      text: "How have you been?",
      language_spans: [
        { language_tag: "en-SG", start_offset: 0, end_offset: 18, confidence: 0.97 },
      ],
      asr_confidence: 0.95,
      audio_quality: 0.92,
      processing_state: "supported",
      processing_reasons: [],
      status: "provisional",
      correction_of_segment_id: null,
      received_at: "2026-09-05T10:00:00Z",
    },
    {
      id: "segment-2",
      sequence: 2,
      chunk_id: "chunk-2",
      start_ms: 120_000,
      end_ms: 123_000,
      speaker_label: "patient",
      text: "Saya allergic to penicillin, bo pian.",
      language_spans: [
        { language_tag: "ms-SG", start_offset: 0, end_offset: 4, confidence: 0.93 },
        { language_tag: "en-SG", start_offset: 4, end_offset: 29, confidence: 0.96 },
        { language_tag: "nan", start_offset: 29, end_offset: 37, confidence: 0.84 },
      ],
      asr_confidence: 0.91,
      audio_quality: 0.86,
      processing_state: "abstained",
      processing_reasons: ["unsupported_provider_language:nan"],
      status: "provisional",
      correction_of_segment_id: null,
      received_at: "2026-09-05T10:02:00Z",
    },
  ],
  safety_signals: [
    {
      id: "signal-1",
      source_segment_id: "segment-2",
      signal_type: "allergy_mention",
      normalized_label: "penicillin",
      evidence_quote: "allergic to penicillin",
      source_start_offset: 5,
      source_end_offset: 27,
      severity: "critical",
      evidence_quality: "adapter_supported_unconfirmed",
      review_state: "provisional",
      review_rationale: null,
      reviewed_by: null,
      detected_at: "2026-09-05T10:02:00Z",
      reviewed_at: null,
    },
  ],
  safety_signal_count: 1,
  finalized_entry_id: null,
  provider_status: null,
  provider_failure_code: null,
  started_at: "2026-09-05T10:00:00Z",
  finalized_at: null,
  assurance_boundary: "Synthetic segments only; no live audio ASR is claimed.",
  ingestion: {
    segment_id: "segment-2",
    replayed: false,
    new_safety_signal_ids: ["signal-1"],
    server_processing_ms: 4.2,
    latency_scope: "API processing only; excludes ASR and network transit",
  },
};

test("scribe streaming rehearsal exposes abstention, provisional review, and finalization", async () => {
  const confirmed: StreamingCapture = {
    ...streamingCapture,
    safety_signals: [
      {
        ...streamingCapture.safety_signals[0],
        review_state: "confirmed",
        reviewed_by: "user-clinician",
      },
    ],
  };
  const finalized: StreamingCapture = {
    ...confirmed,
    status: "finalized_with_abstention",
    finalized_entry_id: "entry-draft",
    provider_status: "live",
    finalized_at: "2026-09-05T10:03:00Z",
  };
  const onRunStreamScenario = vi.fn().mockResolvedValue(streamingCapture);
  const onReviewStreamSignal = vi.fn().mockResolvedValue(confirmed);
  const onFinalizeStream = vi.fn().mockResolvedValue(finalized);
  render(
    <ScribeDialog
      role="clinician"
      onClose={vi.fn()}
      onSubmit={vi.fn()}
      onRunStreamScenario={onRunStreamScenario}
      onReviewStreamSignal={onReviewStreamSignal}
      onFinalizeStream={onFinalizeStream}
    />,
  );

  expect(screen.getByText("No live ASR claim")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /run trilingual stream rehearsal/i }));
  expect(await screen.findByText("Possible penicillin allergy")).toBeVisible();
  expect(screen.getByText("abstained")).toBeVisible();
  expect(screen.getByText("nan · 84%")).toBeVisible();
  expect(screen.getByText(/unsupported provider language:nan/i)).toBeVisible();
  expect(screen.getByText("4.2 ms")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: /confirm with patient/i }));
  await waitFor(() =>
    expect(onReviewStreamSignal).toHaveBeenCalledWith(
      "capture-stream-1",
      "signal-1",
      "confirm",
    ),
  );
  expect(await screen.findByText(/critical floor · confirmed/i)).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: /finalize evidence-safe draft/i }));
  await waitFor(() => expect(onFinalizeStream).toHaveBeenCalledWith("capture-stream-1"));
  expect(await screen.findByText(/finalized with explicit abstention · provider live/i)).toBeVisible();
});

test("scribe streaming rehearsal keeps failures visible and staff signals non-confirmable", async () => {
  const rejected = vi.fn().mockRejectedValue(new Error("Adapter unavailable"));
  const { unmount } = render(
    <ScribeDialog
      role="clinician"
      onClose={vi.fn()}
      onSubmit={vi.fn()}
      onRunStreamScenario={rejected}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /run trilingual stream rehearsal/i }));
  expect(await screen.findByText("Adapter unavailable")).toBeVisible();
  unmount();

  render(
    <ScribeDialog
      role="staff"
      onClose={vi.fn()}
      onSubmit={vi.fn()}
      onRunStreamScenario={vi.fn().mockResolvedValue(streamingCapture)}
      onReviewStreamSignal={vi.fn()}
      onFinalizeStream={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /run trilingual stream rehearsal/i }));
  expect(await screen.findByText("Possible penicillin allergy")).toBeVisible();
  expect(screen.queryByRole("button", { name: /confirm with patient/i })).toBeNull();
});

test("scribe receipt labels deterministic degradation instead of implying AI success", async () => {
  const onSubmit = vi.fn().mockResolvedValue({
    receipt: {},
    flags: ["rule_only_degraded", "provider_deadline_exceeded"],
    clinicalAnchorCount: 2,
    clinicalAnchorsPreserved: true,
    providerStatus: "rule_only_degraded",
    providerFailureCode: "provider_deadline_exceeded",
  });
  render(<ScribeDialog role="clinician" onClose={vi.fn()} onSubmit={onSubmit} />);
  fireEvent.click(screen.getByRole("button", { name: /create review draft/i }));
  expect(await screen.findByText(/AI provider failed \(provider_deadline_exceeded\)/i)).toBeVisible();
  expect(screen.getAllByText("rule only degraded")).toHaveLength(2);
});

test("stream review and finalization errors preserve the source-bound capture", async () => {
  const onReviewStreamSignal = vi.fn().mockRejectedValue(new Error("Review service unavailable"));
  const onFinalizeStream = vi.fn().mockRejectedValue("opaque finalization failure");
  render(
    <ScribeDialog
      role="clinician"
      onClose={vi.fn()}
      onSubmit={vi.fn()}
      onRunStreamScenario={vi.fn().mockResolvedValue({
        ...streamingCapture,
        ingestion: undefined,
      })}
      onReviewStreamSignal={onReviewStreamSignal}
      onFinalizeStream={onFinalizeStream}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /run trilingual stream rehearsal/i }));
  expect(await screen.findByText("- ms")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /dismiss after source review/i }));
  expect(await screen.findByText("Review service unavailable")).toBeVisible();
  expect(onReviewStreamSignal).toHaveBeenCalledWith(
    streamingCapture.id,
    streamingCapture.safety_signals[0].id,
    "dismiss",
  );
  fireEvent.click(screen.getByRole("button", { name: /finalize evidence-safe draft/i }));
  expect(await screen.findByText("Finalization failed.")).toBeVisible();
});

test("opaque signal failures and a finalized no-provider capture are explicit", async () => {
  const onReviewStreamSignal = vi.fn().mockRejectedValue("opaque review failure");
  const finalizedWithoutProvider: StreamingCapture = {
    ...streamingCapture,
    status: "finalized",
    finalized_entry_id: "entry-rule-only",
    finalized_at: "2026-09-05T10:03:00Z",
  };
  const first = render(
    <ScribeDialog
      role="clinician"
      onClose={vi.fn()}
      onSubmit={vi.fn()}
      onRunStreamScenario={vi.fn().mockResolvedValue(streamingCapture)}
      onReviewStreamSignal={onReviewStreamSignal}
      onFinalizeStream={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /run trilingual stream rehearsal/i }));
  await screen.findByText("Possible penicillin allergy");
  fireEvent.click(screen.getByRole("button", { name: /confirm with patient/i }));
  expect(await screen.findByText("Signal review failed.")).toBeVisible();
  first.unmount();

  render(
    <ScribeDialog
      role="clinician"
      onClose={vi.fn()}
      onSubmit={vi.fn()}
      onRunStreamScenario={vi.fn().mockResolvedValue(finalizedWithoutProvider)}
      onReviewStreamSignal={vi.fn()}
      onFinalizeStream={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /run trilingual stream rehearsal/i }));
  expect(await screen.findByText(/provider not invoked/i)).toBeVisible();
});

test("opaque stream adapter failures use a stable fallback", async () => {
  render(
    <ScribeDialog
      role="clinician"
      onClose={vi.fn()}
      onSubmit={vi.fn()}
      onRunStreamScenario={vi.fn().mockRejectedValue("opaque adapter failure")}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /run trilingual stream rehearsal/i }));
  expect(await screen.findByText("Streaming rehearsal failed.")).toBeVisible();
});

test("ordinary finalization errors are shown without replacing the streaming record", async () => {
  render(
    <ScribeDialog
      role="clinician"
      onClose={vi.fn()}
      onSubmit={vi.fn()}
      onRunStreamScenario={vi.fn().mockResolvedValue(streamingCapture)}
      onReviewStreamSignal={vi.fn()}
      onFinalizeStream={vi.fn().mockRejectedValue(new Error("Finalizer unavailable"))}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /run trilingual stream rehearsal/i }));
  await screen.findByText("Possible penicillin allergy");
  fireEvent.click(screen.getByRole("button", { name: /finalize evidence-safe draft/i }));
  expect(await screen.findByText("Finalizer unavailable")).toBeVisible();
});
