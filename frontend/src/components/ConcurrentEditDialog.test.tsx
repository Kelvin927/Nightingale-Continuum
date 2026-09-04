import { fireEvent, render, screen } from "@testing-library/react";

import type { VersionConflictDetail } from "../types";
import { ConcurrentEditDialog } from "./ConcurrentEditDialog";

const detail: VersionConflictDetail = {
  code: "version_conflict",
  message: "The section changed after it was loaded.",
  expected_version: 1,
  current_version: 2,
  current_version_id: "version-2",
  base_snapshot: {
    version_id: "version-1",
    version: 1,
    content: "allergy: pending\nfollow-up: pending\n",
    content_hash: "a".repeat(64),
    created_at: "2026-09-05T08:00:00Z",
  },
  current_snapshot: {
    version_id: "version-2",
    version: 2,
    content: "allergy: pending\nfollow-up: booked\n",
    content_hash: "b".repeat(64),
    created_at: "2026-09-05T08:01:00Z",
  },
  proposed_content: "allergy: reviewed\nfollow-up: pending\n",
  proposed_content_hash: "c".repeat(64),
  merge_assistance: {
    status: "non_overlapping_draft",
    auto_merge_safe: true,
    merged_content: "allergy: reviewed\nfollow-up: booked\n",
    conflicting_hunks: [],
  },
  resolution: "Compare base, current, and proposed content before resubmitting.",
};

test("safe non-overlapping output remains an attested draft", () => {
  const onUseDraft = vi.fn();
  render(
    <ConcurrentEditDialog detail={detail} onClose={vi.fn()} onUseDraft={onUseDraft} />,
  );

  expect(screen.getByText("Base you opened")).toBeVisible();
  expect(screen.getByText("Current record")).toBeVisible();
  expect(screen.getByText("Your unsaved edit")).toBeVisible();
  expect(screen.getByText("Non-overlapping merge draft available")).toBeVisible();
  const open = screen.getByRole("button", { name: /open reviewed draft/i });
  expect(open).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/compared the base, current record, and my draft/i));
  fireEvent.click(open);
  expect(onUseDraft).toHaveBeenCalledWith("allergy: reviewed\nfollow-up: booked\n");
});

test("editing a proposed merge invalidates the prior attestation", () => {
  render(
    <ConcurrentEditDialog detail={detail} onClose={vi.fn()} onUseDraft={vi.fn()} />,
  );
  const reviewed = screen.getByLabelText(/compared the base, current record, and my draft/i);
  const open = screen.getByRole("button", { name: /open reviewed draft/i });
  fireEvent.click(reviewed);
  expect(open).toBeEnabled();
  fireEvent.change(screen.getByLabelText(/^Reviewed draft/i), {
    target: { value: "Clinician-adjusted merge." },
  });
  expect(reviewed).not.toBeChecked();
  expect(open).toBeDisabled();
});

test("overlap and missing current evidence fail closed", () => {
  render(
    <ConcurrentEditDialog
      detail={{
        ...detail,
        current_snapshot: null,
        merge_assistance: {
          status: "manual_review_required",
          auto_merge_safe: false,
          merged_content: null,
          conflicting_hunks: [
            {
              base_start_line: 1,
              base_end_line: 1,
              proposed_text: "dose: 20 mg",
              current_text: "dose: 30 mg",
            },
          ],
        },
      }}
      onClose={vi.fn()}
      onUseDraft={vi.fn()}
    />,
  );
  expect(screen.getByText("Manual reconciliation required")).toBeVisible();
  expect(screen.getByText(/current version unavailable/i)).toBeVisible();
  fireEvent.click(screen.getByLabelText(/compared the base, current record, and my draft/i));
  expect(screen.getByRole("button", { name: /open reviewed draft/i })).toBeDisabled();
});
