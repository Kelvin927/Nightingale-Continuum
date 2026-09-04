import { fireEvent, render, screen } from "@testing-library/react";

import { deliveryReadiness, patientInstruction } from "../test/fixtures";
import type { DeliveryItem } from "../types";
import { DeliveryCenter } from "./DeliveryCenter";

const delivered: DeliveryItem = {
  id: "delivery-original",
  source_entry_id: patientInstruction.id,
  source_version_id: "version-old",
  source_is_current: false,
  correction_for_id: null,
  channel: "whatsapp",
  masked_destination: "WhatsApp ending 4567",
  content_snapshot: "Take lisinopril 20 mg daily.",
  content_hash: "c".repeat(64),
  status: "delivered",
  receipt_meaning: "Provider delivery receipt recorded",
  attempt_count: 1,
  created_at: "2026-09-05T00:00:00Z",
  accepted_at: "2026-09-05T00:01:00Z",
  delivered_at: "2026-09-05T00:02:00Z",
  superseded_at: null,
};

function props() {
  return {
    readiness: deliveryReadiness,
    role: "clinician" as const,
    patientFacingEntries: [patientInstruction],
    busy: false,
    onQueue: vi.fn().mockResolvedValue(undefined),
    onCorrect: vi.fn().mockResolvedValue(undefined),
    onTransition: vi.fn().mockResolvedValue(undefined),
  };
}

test("clinician queue requires exact-copy, identity, and dose attestations", () => {
  const values = props();
  render(<DeliveryCenter {...values} />);
  expect(screen.getByText(/WhatsApp ending 4567/)).toBeVisible();
  const queue = screen.getByRole("button", { name: /queue approved copy/i });
  expect(queue).toBeDisabled();

  fireEvent.click(screen.getByLabelText(/reviewed the exact patient-facing copy/i));
  fireEvent.click(screen.getByLabelText(/verified the patient and contact route/i));
  expect(queue).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/verified every medication and dose/i));
  expect(queue).toBeEnabled();
  fireEvent.click(queue);
  expect(values.onQueue).toHaveBeenCalledWith(
    patientInstruction,
    "contact-whatsapp",
    { clinical: true, identity: true, medication: true },
  );
});

test("stale delivered copy remains visible and supports an explicit correction", () => {
  const values = props();
  render(
    <DeliveryCenter
      {...values}
      readiness={{ ...deliveryReadiness, deliveries: [delivered] }}
    />,
  );
  expect(screen.getByText(/source note has changed/i)).toBeVisible();
  fireEvent.click(screen.getByText(/view immutable sent copy/i));
  expect(screen.getByText("Take lisinopril 20 mg daily.")).toBeVisible();
  const correction = screen.getByRole("button", { name: /queue current version as correction/i });
  expect(correction).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/reviewed the exact patient-facing copy/i));
  fireEvent.click(screen.getByLabelText(/verified the patient and contact route/i));
  fireEvent.click(screen.getByLabelText(/verified every medication and dose/i));
  fireEvent.click(correction);
  expect(values.onCorrect).toHaveBeenCalledWith(
    delivered,
    patientInstruction,
    "contact-whatsapp",
    { clinical: true, identity: true, medication: true },
  );
});

test("patient view hides approval controls and admin simulator advances one receipt step", () => {
  const accepted = { ...delivered, id: "delivery-accepted", status: "accepted" as const };
  const patientView = props();
  const first = render(
    <DeliveryCenter
      {...patientView}
      role="patient"
      readiness={{ ...deliveryReadiness, deliveries: [] }}
    />,
  );
  expect(screen.queryByRole("button", { name: /queue approved copy/i })).toBeNull();
  first.unmount();

  const adminView = props();
  render(
    <DeliveryCenter
      {...adminView}
      role="admin"
      readiness={{
        ...deliveryReadiness,
        deliveries: [{ ...delivered, id: "delivery-queued", status: "queued" }, accepted],
      }}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /record synthetic provider acceptance/i }));
  expect(adminView.onTransition).toHaveBeenCalledWith(
    expect.objectContaining({ id: "delivery-queued" }),
    "accepted",
  );
  fireEvent.click(screen.getByRole("button", { name: /record synthetic delivery receipt/i }));
  expect(adminView.onTransition).toHaveBeenCalledWith(accepted, "delivered");
});

test("missing route and empty ledger fail visibly without creating an action", () => {
  const values = props();
  render(
    <DeliveryCenter
      {...values}
      readiness={{ ...deliveryReadiness, contacts: [], deliveries: [] }}
    />,
  );
  expect(screen.getByText("No ready route")).toBeVisible();
  expect(screen.getByText(/No patient communication has been queued/i)).toBeVisible();
  expect(screen.getByRole("button", { name: /queue approved copy/i })).toBeDisabled();
});
