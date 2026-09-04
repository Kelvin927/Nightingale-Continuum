import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import {
  deliveryReadiness,
  patient,
  patientEntry,
  patientInstruction,
  workspace,
} from "../test/fixtures";
import type { PatientAccessClaim, PatientAccessProof } from "../types";
import { PatientAccessDialog } from "./PatientAccessDialog";

const claim: PatientAccessClaim = {
  claim_id: "claim-1",
  patient_id: patient.id,
  channel: "whatsapp",
  masked_destination: "WhatsApp ending 4567",
  purpose: "portal_access",
  status: "issued",
  expires_at: "2026-09-05T11:10:00Z",
  delivery_state: "synthetic_rehearsal_not_sent",
  demo_claim_token: "synthetic-one-time-secret",
  security_note: "Plaintext is returned only for this synthetic rehearsal.",
};

const proof: PatientAccessProof = {
  viewer: {
    id: "user-patient",
    display_name: patient.display_name,
    role: "patient",
    clinic_id: "clinic-1",
    patient_id: patient.id,
    authentication_mode: "channel_claim",
  },
  workspace: {
    ...workspace,
    viewer: { id: "user-patient", role: "patient" },
    entries: [patientEntry, patientInstruction],
    conflicts: [],
  },
  grant_expires_at: "2026-09-05T11:30:00Z",
  email_required: false,
};

type IssueHandler = (payload: {
  contactId: string;
  purpose: PatientAccessClaim["purpose"];
  ttlMinutes: number;
}) => Promise<PatientAccessClaim>;
type RedeemHandler = (payload: {
  claimToken: string;
  recordNumber: string;
  dateOfBirth: string;
}) => Promise<PatientAccessProof>;

function renderDialog(overrides?: {
  onIssue?: IssueHandler;
  onRedeem?: RedeemHandler;
}) {
  const onIssue = vi.fn<IssueHandler>(overrides?.onIssue ?? (async () => claim));
  const onRedeem = vi.fn<RedeemHandler>(overrides?.onRedeem ?? (async () => proof));
  render(
    <PatientAccessDialog
      patient={patient}
      contact={deliveryReadiness.contacts[0]}
      onClose={vi.fn()}
      onIssue={onIssue}
      onRedeem={onRedeem}
    />,
  );
  return { onIssue, onRedeem };
}

test("phone-only rehearsal issues one claim and proves the patient-only projection", async () => {
  const { onIssue, onRedeem } = renderDialog();
  const dialog = screen.getByRole("dialog");

  expect(within(dialog).getByText("No email dependency")).toBeVisible();
  expect(within(dialog).getByText("Patient-only projection")).toBeVisible();
  fireEvent.change(within(dialog).getByLabelText("Access purpose"), {
    target: { value: "instructions" },
  });
  fireEvent.change(within(dialog).getByLabelText("Claim lifetime"), {
    target: { value: "15" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: /create one-time access claim/i }));

  await waitFor(() => expect(onIssue).toHaveBeenCalledWith({
    contactId: "contact-whatsapp",
    purpose: "instructions",
    ttlMinutes: 15,
  }));
  expect(await within(dialog).findByText("synthetic-one-time-secret")).toBeVisible();
  expect(within(dialog).getByText(/no message was sent/i)).toBeVisible();
  fireEvent.change(within(dialog).getByLabelText("Synthetic record number"), {
    target: { value: "TEMP" },
  });
  fireEvent.change(within(dialog).getByLabelText("Synthetic record number"), {
    target: { value: patient.synthetic_record_number },
  });
  fireEvent.change(within(dialog).getByLabelText("Date of birth"), {
    target: { value: "2000-01-01" },
  });
  fireEvent.change(within(dialog).getByLabelText("Date of birth"), {
    target: { value: patient.date_of_birth },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: /verify and open patient view/i }));

  await waitFor(() => expect(onRedeem).toHaveBeenCalledWith({
    claimToken: claim.demo_claim_token,
    recordNumber: patient.synthetic_record_number,
    dateOfBirth: patient.date_of_birth,
  }));
  expect(await within(dialog).findByText("Authenticated without email")).toBeVisible();
  expect(within(dialog).getByText("channel claim")).toBeVisible();
  expect(within(dialog).getByText("2 visible entries")).toBeVisible();
  expect(within(dialog).getByText(patientInstruction.title)).toBeVisible();
  expect(within(dialog).queryByText("Assessment and plan")).toBeNull();
});

test("claim issue and verification failures remain explicit without fabricating access", async () => {
  const issueFailure: IssueHandler = async () => {
    throw new Error("Verified channel unavailable.");
  };
  const first = renderDialog({ onIssue: issueFailure });
  fireEvent.click(screen.getByRole("button", { name: /create one-time access claim/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Verified channel unavailable.");
  expect(first.onRedeem).not.toHaveBeenCalled();
});

test("generic redemption failure permits a fresh claim without exposing an authenticated view", async () => {
  const onRedeem: RedeemHandler = async () => {
    throw new Error("The access claim could not be verified");
  };
  const { onIssue } = renderDialog({ onRedeem });
  fireEvent.click(screen.getByRole("button", { name: /create one-time access claim/i }));
  await screen.findByText("synthetic-one-time-secret");
  fireEvent.click(screen.getByRole("button", { name: /verify and open patient view/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The access claim could not be verified",
  );
  expect(screen.queryByText("Authenticated without email")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Issue another" }));
  expect(screen.getByRole("button", { name: /create one-time access claim/i })).toBeVisible();
  expect(onIssue).toHaveBeenCalledTimes(1);
});

test("non-WhatsApp routes and opaque callback failures keep the rehearsal closed", async () => {
  const opaqueIssue: IssueHandler = async () => Promise.reject("opaque issue");
  render(
    <PatientAccessDialog
      patient={patient}
      contact={{ ...deliveryReadiness.contacts[0], channel: "sms" }}
      onClose={vi.fn()}
      onIssue={opaqueIssue}
      onRedeem={async () => proof}
    />,
  );
  expect(screen.getByText("sms")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /create one-time access claim/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The access claim was not issued.");
});

test("opaque redemption errors use the generic message", async () => {
  const opaqueRedeem: RedeemHandler = async () => Promise.reject("opaque redemption");
  renderDialog({ onRedeem: opaqueRedeem });
  fireEvent.click(screen.getByRole("button", { name: /create one-time access claim/i }));
  await screen.findByText("synthetic-one-time-secret");
  fireEvent.click(screen.getByRole("button", { name: /verify and open patient view/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The access claim could not be verified.",
  );
});

test("pending operations remain visibly busy and an empty patient projection is explicit", async () => {
  let resolveIssue!: (value: PatientAccessClaim) => void;
  let resolveRedeem!: (value: PatientAccessProof) => void;
  const issuePending: IssueHandler = () => new Promise((resolve) => { resolveIssue = resolve; });
  const redeemPending: RedeemHandler = () => new Promise((resolve) => { resolveRedeem = resolve; });
  renderDialog({ onIssue: issuePending, onRedeem: redeemPending });

  fireEvent.click(screen.getByRole("button", { name: /create one-time access claim/i }));
  expect(screen.getByRole("button", { name: /issuing safely/i })).toBeDisabled();
  await act(async () => resolveIssue(claim));
  fireEvent.click(screen.getByRole("button", { name: /verify and open patient view/i }));
  expect(screen.getByRole("button", { name: /verifying scope/i })).toBeDisabled();
  await act(async () => resolveRedeem({
    ...proof,
    workspace: { ...proof.workspace, entries: [] },
  }));
  expect(screen.getByText("0 visible entries")).toBeVisible();
  expect(screen.getByText(/No clinician-approved patient-facing entry/i)).toBeVisible();
});

test("a single patient-facing record uses the singular projection label", async () => {
  renderDialog({
    onRedeem: async () => ({
      ...proof,
      workspace: { ...proof.workspace, entries: [patientInstruction] },
    }),
  });
  fireEvent.click(screen.getByRole("button", { name: /create one-time access claim/i }));
  await screen.findByText("synthetic-one-time-secret");
  fireEvent.click(screen.getByRole("button", { name: /verify and open patient view/i }));
  expect(await screen.findByText("1 visible entry")).toBeVisible();
});
