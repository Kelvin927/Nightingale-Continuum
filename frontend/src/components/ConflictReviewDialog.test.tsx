import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { workspace } from "../test/fixtures";
import type { ConflictItem } from "../types";
import { ConflictReviewDialog } from "./ConflictReviewDialog";

const openConflict = workspace.conflicts[0];

test("clinician must review both immutable sources and document a rationale", async () => {
  const onResolve = vi.fn().mockResolvedValue(undefined);
  render(
    <ConflictReviewDialog
      conflict={openConflict}
      role="clinician"
      busy={false}
      onClose={vi.fn()}
      onResolve={onResolve}
    />,
  );

  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("Current source")).toBeVisible();
  expect(within(dialog).getByText("Stale source")).toBeVisible();
  expect(within(dialog).getByText(/sha256 a+/i)).toBeVisible();
  const escalation = within(dialog).getByRole("button", { name: /escalate unresolved/i });
  expect(escalation).toBeDisabled();

  fireEvent.click(within(dialog).getByLabelText(/reviewed both immutable source versions/i));
  fireEvent.change(within(dialog).getByLabelText(/clinical rationale/i), {
    target: { value: "short" },
  });
  expect(escalation).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText(/clinical rationale/i), {
    target: { value: "Both assertions need confirmation from the dispensing record." },
  });
  fireEvent.click(escalation);
  await waitFor(() => expect(onResolve).toHaveBeenCalledWith(
    "escalate_unresolved",
    "Both assertions need confirmation from the dispensing record.",
    true,
  ));
});

test("unavailable evidence fails closed and non-clinicians cannot decide", () => {
  const conflict: ConflictItem = {
    ...openConflict,
    left: {
      state: "unavailable",
      version_id: "missing-version",
    },
  };
  render(
    <ConflictReviewDialog
      conflict={conflict}
      role="staff"
      busy={false}
      onClose={vi.fn()}
      onResolve={vi.fn()}
    />,
  );

  expect(screen.getByRole("heading", { name: "Source unavailable" })).toBeVisible();
  expect(screen.getByText(/must remain unresolved/i)).toBeVisible();
  expect(screen.getByText("Clinician review required")).toBeVisible();
  expect(screen.queryByRole("button", { name: /confirm assertion/i })).toBeNull();
});

test("resolved conflict shows the audited rationale without decision controls", () => {
  render(
    <ConflictReviewDialog
      conflict={{
        ...openConflict,
        status: "resolved",
        resolution: {
          decision: "confirm_left",
          rationale: "Verified against the signed medication administration record.",
          resolved_by: "user-clinician",
        },
      }}
      role="clinician"
      busy={false}
      onClose={vi.fn()}
      onResolve={vi.fn()}
    />,
  );

  expect(screen.getByText("resolved")).toBeVisible();
  expect(screen.getByText(/signed medication administration record/i)).toBeVisible();
  expect(screen.queryByRole("button", { name: /confirm assertion/i })).toBeNull();
});

test("resolution failures remain actionable in the dialog", async () => {
  const onResolve = vi.fn().mockRejectedValue(new Error("Decision service unavailable."));
  render(
    <ConflictReviewDialog
      conflict={openConflict}
      role="clinician"
      busy={false}
      onClose={vi.fn()}
      onResolve={onResolve}
    />,
  );

  fireEvent.click(screen.getByLabelText(/reviewed both immutable source versions/i));
  fireEvent.change(screen.getByLabelText(/clinical rationale/i), {
    target: { value: "Reviewed both immutable source records." },
  });
  fireEvent.click(screen.getByRole("button", { name: /confirm assertion a/i }));
  expect(await screen.findByText("Decision service unavailable.")).toBeVisible();
});
