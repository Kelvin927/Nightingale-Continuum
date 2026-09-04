import { fireEvent, render, screen } from "@testing-library/react";

import { deliveryReadiness, patientInstruction } from "../test/fixtures";
import type { DeliveryItem, Entry, TerminologyAssessment } from "../types";
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

const plainEntry: Entry = {
  ...patientInstruction,
  id: "entry-plain-summary",
  title: "Plain follow-up summary",
  version: {
    ...patientInstruction.version,
    id: "version-plain-summary",
    content: "Your next visit is booked for Monday.",
  },
};

const structuredAssessment = deliveryReadiness.terminology_assessments?.[0] as TerminologyAssessment;
const plainAssessment: TerminologyAssessment = {
  ...structuredAssessment,
  entry_id: plainEntry.id,
  source_version_id: plainEntry.version.id,
  status: "not_applicable",
  dose_sensitive: false,
  human_confirmation_required: false,
  semantic_review_required: false,
  medication_mentions: [],
  dose_mentions: [],
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
  expect(screen.getByText("Structured medication evidence ready")).toBeVisible();
  expect(screen.getByText("20 mg")).toBeVisible();
  fireEvent.click(screen.getByText(/what this check does/i));
  expect(screen.getByText(/does not establish prescription accuracy/i)).toBeVisible();
  expect(screen.getByText(/no external terminology lookup was performed/i)).toBeVisible();
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

test("entry selection recalculates a non-medication approval contract", () => {
  const values = props();
  render(
    <DeliveryCenter
      {...values}
      patientFacingEntries={[patientInstruction, plainEntry]}
      readiness={{
        ...deliveryReadiness,
        terminology_assessments: [structuredAssessment, plainAssessment],
      }}
    />,
  );
  fireEvent.click(screen.getByLabelText(/reviewed the exact patient-facing copy/i));
  fireEvent.click(screen.getByLabelText(/verified the patient and contact route/i));
  fireEvent.click(screen.getByLabelText(/verified every medication and dose/i));
  fireEvent.change(screen.getByLabelText("Patient-facing source"), {
    target: { value: plainEntry.id },
  });
  expect(screen.getByText("No medication or dose signal detected")).toBeVisible();
  expect(screen.getByRole("button", { name: /queue approved copy/i })).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/reviewed the exact patient-facing copy/i));
  fireEvent.click(screen.getByLabelText(/verified the patient and contact route/i));
  const queue = screen.getByRole("button", { name: /queue approved copy/i });
  expect(screen.getByText(/verified every medication and dose \(if present\)/i)).toBeVisible();
  expect(queue).toBeEnabled();
  fireEvent.click(queue);
  expect(values.onQueue).toHaveBeenCalledWith(
    plainEntry,
    "contact-whatsapp",
    { clinical: true, identity: true, medication: false },
  );
});

test("missing or unresolved terminology evidence fails closed with a visible reason", () => {
  const values = props();
  const first = render(
    <DeliveryCenter
      {...values}
      readiness={{ ...deliveryReadiness, terminology_assessments: undefined }}
    />,
  );
  expect(screen.getByText(/assessment unavailable.*release blocked/i)).toBeVisible();
  expect(screen.getByRole("button", { name: /queue approved copy/i })).toBeDisabled();
  first.unmount();

  const unresolved: TerminologyAssessment = {
    ...structuredAssessment,
    status: "blocked_unresolved",
    release_permitted_after_confirmation: false,
    dose_mentions: [{
      source_text: "25 mg",
      source_start: 5,
      source_end: 10,
      normalized_value: "25",
      normalized_unit: "mg",
      medication_name: null,
    }],
    unresolved: [{
      code: "unlinked_dose",
      source_text: "25 mg",
      source_start: 5,
      source_end: 10,
      message: "This dose is not linked to a supported medication name.",
    }],
  };
  render(
    <DeliveryCenter
      {...values}
      readiness={{ ...deliveryReadiness, terminology_assessments: [unresolved] }}
    />,
  );
  expect(screen.getByText(/unresolved terminology.*release blocked/i)).toBeVisible();
  expect(screen.getByText(/this dose is not linked/i)).toBeVisible();
  expect(screen.getByText("Unlinked dose")).toBeVisible();
});

test("human-only and contrastive states disclose their limits", () => {
  const values = props();
  const humanOnly: TerminologyAssessment = {
    ...structuredAssessment,
    status: "human_review_only",
    dose_mentions: [],
  };
  const first = render(
    <DeliveryCenter
      {...values}
      readiness={{ ...deliveryReadiness, terminology_assessments: [humanOnly] }}
    />,
  );
  expect(screen.getByText(/human review only.*no structured dose pair/i)).toBeVisible();
  expect(screen.getByText(/no structured medication-dose pair/i)).toBeVisible();
  first.unmount();

  render(
    <DeliveryCenter
      {...values}
      readiness={{
        ...deliveryReadiness,
        terminology_assessments: [{ ...structuredAssessment, semantic_review_required: true }],
      }}
    />,
  );
  expect(screen.getByText(/scanner does not infer clinical intent/i)).toBeVisible();
});

test("failed, superseded, and correction delivery states remain distinguishable", () => {
  const values = props();
  render(
    <DeliveryCenter
      {...values}
      readiness={{
        ...deliveryReadiness,
        contacts: deliveryReadiness.contacts.map((contact) => ({ ...contact, preferred: false })),
        deliveries: [
          { ...delivered, id: "delivery-failed", status: "failed" },
          { ...delivered, id: "delivery-superseded", status: "superseded" },
          {
            ...delivered,
            id: "delivery-correction",
            correction_for_id: "delivery-original",
            source_is_current: true,
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("failed")).toBeVisible();
  expect(screen.getByText("superseded")).toBeVisible();
  expect(screen.getByText("Correction")).toBeVisible();
  expect(screen.getAllByText(/WhatsApp ending 4567/).length).toBeGreaterThan(0);
});

test("an empty patient-facing catalogue has no selected source", () => {
  const values = props();
  render(<DeliveryCenter {...values} patientFacingEntries={[]} />);
  expect(
    (screen.getByLabelText("Patient-facing source") as HTMLSelectElement).options,
  ).toHaveLength(0);
  expect(screen.getByRole("button", { name: /queue approved copy/i })).toBeDisabled();
});
