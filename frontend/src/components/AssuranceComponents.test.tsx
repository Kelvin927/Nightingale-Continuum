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
  const handlers = { onHistory: vi.fn(), onEdit: vi.fn(), onComment: vi.fn() };
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
