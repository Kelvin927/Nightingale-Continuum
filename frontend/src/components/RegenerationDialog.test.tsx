import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { aiEntry } from "../test/fixtures";
import type { RegenerationResult } from "../types";
import { RegenerationDialog } from "./RegenerationDialog";

const result: RegenerationResult = {
  entry_id: "entry-new-proposal",
  predecessor_entry_id: aiEntry.id,
  status: "new_ai_proposal_created",
  provider: "local-deterministic-scribe",
  provider_status: "live",
  provider_failure_code: null,
  flags: ["human_review_required"],
  preservation_receipt: {
    unchanged: true,
    protected_state_hash: "a".repeat(64),
    protected_highlight_count: 3,
    completed_task_count: 2,
    resolved_conflict_count: 1,
    released_delivery_count: 1,
    reviewed_signal_count: 1,
    meaning: "A new proposal was created and protected state was not modified.",
  },
};

test("regeneration shows a protected-state receipt rather than replacing the prior entry", async () => {
  const onRegenerate = vi.fn().mockResolvedValue(result);
  render(
    <RegenerationDialog entry={aiEntry} onClose={vi.fn()} onRegenerate={onRegenerate} />,
  );
  expect(screen.getByText(/only a new ai proposal may be created/i)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /create separate proposal/i }));
  await waitFor(() => expect(onRegenerate).toHaveBeenCalledWith(
    expect.stringContaining("synthetic rehearsal"),
  ));
  expect(await screen.findByText("Protected state unchanged")).toBeVisible();
  expect(screen.getByText("3")).toBeVisible();
  expect(screen.getByText(/state sha256 a+/i)).toBeVisible();
  expect(screen.getByRole("button", { name: /return to timeline/i })).toBeVisible();
});

test("regeneration failures remain in the proposal dialog", async () => {
  const onRegenerate = vi.fn().mockRejectedValue(new Error("Provider boundary unavailable."));
  render(
    <RegenerationDialog entry={aiEntry} onClose={vi.fn()} onRegenerate={onRegenerate} />,
  );
  fireEvent.click(screen.getByRole("button", { name: /create separate proposal/i }));
  expect(await screen.findByText("Provider boundary unavailable.")).toBeVisible();
  expect(screen.getByRole("button", { name: /create separate proposal/i })).toBeEnabled();
});

test("short transcripts are blocked before submission", () => {
  const onRegenerate = vi.fn();
  render(
    <RegenerationDialog entry={aiEntry} onClose={vi.fn()} onRegenerate={onRegenerate} />,
  );
  fireEvent.change(screen.getByLabelText(/corrected source transcript/i), {
    target: { value: "tiny" },
  });
  expect(screen.getByRole("button", { name: /create separate proposal/i })).toBeDisabled();
});

test("opaque regeneration failures use the fail-closed message", async () => {
  const onRegenerate = vi.fn().mockRejectedValue("opaque failure");
  render(
    <RegenerationDialog entry={aiEntry} onClose={vi.fn()} onRegenerate={onRegenerate} />,
  );
  fireEvent.click(screen.getByRole("button", { name: /create separate proposal/i }));
  expect(await screen.findByText("Regeneration failed safely.")).toBeVisible();
});
