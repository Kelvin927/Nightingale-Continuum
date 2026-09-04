import { fireEvent, render, screen } from "@testing-library/react";

import { deliveryReadiness, patientInstruction } from "../test/fixtures";
import type { DeliveryItem, Entry, TerminologyAssessment } from "../types";
import { DeliveryCenter } from "./DeliveryCenter";

const delivered: DeliveryItem = {
  id: "delivery-original",
  patient_id: patientInstruction.patient_id,
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
  communication_purpose: "care_summary",
  follow_up: null,
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

const appointmentEntry: Entry = {
  ...plainEntry,
  id: "entry-appointment",
  title: "Your follow-up appointment",
  version: {
    ...plainEntry.version,
    id: "version-appointment",
    content: "Your appointment is 10 September 2026 at 09:30 SGT. Open https://appointments.example.test/synthetic/follow-up-2048.",
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
const appointmentAssessment: TerminologyAssessment = {
  ...plainAssessment,
  entry_id: appointmentEntry.id,
  source_version_id: appointmentEntry.version.id,
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
    onAcknowledge: vi.fn().mockResolvedValue(undefined),
    onSweep: vi.fn().mockResolvedValue(undefined),
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
    "care_summary",
    { clinical: true, identity: true, medication: true, appointment: false },
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
    { clinical: true, identity: true, medication: true, appointment: false },
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
  fireEvent.click(screen.getByRole("button", { name: /check failed or overdue/i }));
  expect(adminView.onSweep).toHaveBeenCalledTimes(1);
});

test("appointment purpose requires a separate detail attestation and queues an acknowledgement contract", () => {
  const values = props();
  render(
    <DeliveryCenter
      {...values}
      patientFacingEntries={[appointmentEntry]}
      readiness={{ ...deliveryReadiness, terminology_assessments: [appointmentAssessment] }}
    />,
  );
  fireEvent.change(screen.getByLabelText("Communication purpose"), {
    target: { value: "appointment_invitation" },
  });
  expect(screen.getByText(/acknowledgement required/i)).toBeVisible();
  fireEvent.click(screen.getByLabelText(/reviewed the exact patient-facing copy/i));
  fireEvent.click(screen.getByLabelText(/verified the patient and contact route/i));
  const queue = screen.getByRole("button", { name: /queue approved copy/i });
  expect(queue).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/verified the appointment date, time, location, and exact link/i));
  expect(queue).toBeEnabled();
  fireEvent.click(queue);
  expect(values.onQueue).toHaveBeenCalledWith(
    appointmentEntry,
    "contact-whatsapp",
    "appointment_invitation",
    { clinical: true, identity: true, medication: false, appointment: true },
  );

  fireEvent.change(screen.getByLabelText("Communication purpose"), {
    target: { value: "patient_instruction" },
  });
  expect(screen.queryByLabelText(/verified the appointment date/i)).toBeNull();
});

test("appointment ledger separates pending, overdue escalation, and patient acknowledgement", () => {
  const awaiting: DeliveryItem = {
    ...delivered,
    id: "delivery-awaiting-appointment",
    communication_purpose: "appointment_invitation",
    follow_up: {
      id: "follow-up-awaiting",
      purpose: "appointment_invitation",
      status: "awaiting_patient_acknowledgement",
      acknowledgement_window_minutes: 1_440,
      acknowledge_by: "2026-09-06T09:02:00Z",
      acknowledged_at: null,
      escalated_at: null,
      requires_patient_acknowledgement: true,
    },
  };
  const escalated: DeliveryItem = {
    ...awaiting,
    id: "delivery-escalated-appointment",
    follow_up: {
      ...awaiting.follow_up!,
      id: "follow-up-escalated",
      status: "escalated",
      escalated_at: "2026-09-06T09:03:00Z",
    },
  };
  const acknowledged: DeliveryItem = {
    ...awaiting,
    id: "delivery-acknowledged-appointment",
    follow_up: {
      ...awaiting.follow_up!,
      id: "follow-up-acknowledged",
      status: "acknowledged_after_escalation",
      acknowledged_at: "2026-09-06T10:00:00Z",
      escalated_at: "2026-09-06T09:03:00Z",
    },
  };
  const pendingProvider: DeliveryItem = {
    ...awaiting,
    id: "delivery-pending-provider",
    status: "queued",
    follow_up: {
      ...awaiting.follow_up!,
      id: "follow-up-pending-provider",
      status: "pending_provider_acceptance",
      acknowledge_by: null,
    },
  };
  const values = props();
  render(
    <DeliveryCenter
      {...values}
      role="patient"
      readiness={{
        ...deliveryReadiness,
        deliveries: [awaiting, escalated, acknowledged, pendingProvider],
      }}
    />,
  );
  expect(screen.getAllByText(/patient acknowledgement due/i)).toHaveLength(3);
  expect(screen.getByText(/patient confirmed/i)).toBeVisible();
  expect(screen.getByText(/acknowledgement clock starts only after/i)).toBeVisible();
  const acknowledge = screen.getAllByRole("button", {
    name: /i received this appointment invitation/i,
  });
  expect(acknowledge).toHaveLength(2);
  fireEvent.click(acknowledge[1]);
  expect(values.onAcknowledge).toHaveBeenCalledWith(escalated);
  expect(screen.queryByRole("button", { name: /check failed or overdue/i })).toBeNull();
});

test("an appointment correction cannot reuse approval state under a different purpose", () => {
  const values = props();
  const staleAppointment: DeliveryItem = {
    ...delivered,
    source_entry_id: appointmentEntry.id,
    communication_purpose: "appointment_invitation",
    follow_up: null,
  };
  render(
    <DeliveryCenter
      {...values}
      patientFacingEntries={[appointmentEntry]}
      readiness={{
        ...deliveryReadiness,
        deliveries: [staleAppointment],
        terminology_assessments: [appointmentAssessment],
      }}
    />,
  );
  fireEvent.click(screen.getByLabelText(/reviewed the exact patient-facing copy/i));
  fireEvent.click(screen.getByLabelText(/verified the patient and contact route/i));
  expect(screen.getByRole("button", { name: /queue current version as correction/i })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Communication purpose"), {
    target: { value: "appointment_invitation" },
  });
  expect(screen.getByRole("button", { name: /queue current version as correction/i })).toBeDisabled();
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
    "care_summary",
    { clinical: true, identity: true, medication: false, appointment: false },
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
