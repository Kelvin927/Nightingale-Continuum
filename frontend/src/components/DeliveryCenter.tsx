import { useMemo, useState } from "react";
import {
  CheckCircle2,
  CircleAlert,
  Clock3,
  MessageCircleMore,
  RefreshCw,
  Send,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import type {
  DeliveryItem,
  DeliveryReadiness,
  Entry,
  Role,
  TerminologyAssessment,
} from "../types";

interface Attestations {
  clinical: boolean;
  identity: boolean;
  medication: boolean;
  appointment: boolean;
}

interface Props {
  readiness: DeliveryReadiness;
  role: Role;
  patientFacingEntries: Entry[];
  busy: boolean;
  onQueue: (
    entry: Entry,
    contactId: string,
    purpose: DeliveryItem["communication_purpose"],
    attestations: Attestations,
  ) => Promise<void>;
  onCorrect: (
    original: DeliveryItem,
    entry: Entry,
    contactId: string,
    attestations: Attestations,
  ) => Promise<void>;
  onTransition: (
    delivery: DeliveryItem,
    outcome: "queued" | "accepted" | "delivered" | "failed",
  ) => Promise<void>;
  onAcknowledge: (delivery: DeliveryItem) => Promise<void>;
  onSweep: () => Promise<void>;
}

function StatusIcon({ status }: { status: DeliveryItem["status"] }) {
  if (status === "delivered") return <CheckCircle2 size={15} />;
  if (status === "failed") return <XCircle size={15} />;
  if (status === "accepted") return <Clock3 size={15} />;
  if (status === "superseded") return <RefreshCw size={15} />;
  return <Send size={15} />;
}

function terminologyLabel(assessment: TerminologyAssessment | undefined) {
  if (!assessment) return "Assessment unavailable — release blocked";
  if (assessment.status === "blocked_unresolved") return "Unresolved terminology — release blocked";
  if (assessment.status === "structured_review_ready") return "Structured medication evidence ready";
  if (assessment.status === "human_review_only") return "Human review only — no structured dose pair";
  return "No medication or dose signal detected";
}

export function DeliveryCenter({
  readiness,
  role,
  patientFacingEntries,
  busy,
  onQueue,
  onCorrect,
  onTransition,
  onAcknowledge,
  onSweep,
}: Props) {
  const [selectedEntryId, setSelectedEntryId] = useState(patientFacingEntries[0]?.id ?? "");
  const [purpose, setPurpose] = useState<DeliveryItem["communication_purpose"]>("care_summary");
  const [attestations, setAttestations] = useState<Attestations>({
    clinical: false,
    identity: false,
    medication: false,
    appointment: false,
  });
  const preferredContact = readiness.contacts.find((contact) => contact.preferred)
    ?? readiness.contacts[0];
  const selectedEntry = patientFacingEntries.find((entry) => entry.id === selectedEntryId)
    ?? patientFacingEntries[0];
  const terminology = readiness.terminology_assessments?.find(
    (item) => item.entry_id === selectedEntry?.id
      && item.source_version_id === selectedEntry?.version.id,
  );
  const doseSensitive = terminology?.human_confirmation_required ?? false;
  const terminologyReady = Boolean(terminology?.release_permitted_after_confirmation);
  const appointmentSelected = purpose === "appointment_invitation";
  const readyToQueue = Boolean(
    selectedEntry
    && preferredContact
    && preferredContact.active
    && preferredContact.verified
    && preferredContact.consent_status === "granted"
    && attestations.clinical
    && attestations.identity
    && terminologyReady
    && (!doseSensitive || attestations.medication)
    && (!appointmentSelected || attestations.appointment),
  );
  const entriesById = useMemo(
    () => new Map(patientFacingEntries.map((entry) => [entry.id, entry])),
    [patientFacingEntries],
  );

  function toggle(key: keyof Attestations) {
    setAttestations((current) => ({ ...current, [key]: !current[key] }));
  }
  function selectEntry(entryId: string) {
    setSelectedEntryId(entryId);
    setPurpose("care_summary");
    setAttestations({
      clinical: false,
      identity: false,
      medication: false,
      appointment: false,
    });
  }

  function selectPurpose(next: DeliveryItem["communication_purpose"]) {
    setPurpose(next);
    setAttestations((current) => ({ ...current, appointment: false }));
  }

  return (
    <section className="delivery-center" aria-labelledby="delivery-title">
      <div className="delivery-heading">
        <div>
          <span className="eyebrow">Closed-loop communication</span>
          <h2 id="delivery-title">Delivery assurance</h2>
          <p>Provider acceptance is tracked separately from confirmed patient delivery.</p>
        </div>
        <div className="contact-route">
          <MessageCircleMore size={17} />
          {preferredContact ? (
            <span>
              <strong>{preferredContact.channel}</strong>
              <small>{preferredContact.masked_destination} · verified · consented</small>
            </span>
          ) : (
            <span><strong>No ready route</strong><small>Add and verify patient consent first</small></span>
          )}
        </div>
      </div>

      {role === "clinician" && (
        <div className="delivery-approval">
          <div className="delivery-source-controls">
            <label>
              Patient-facing source
              <select
                aria-label="Patient-facing source"
                value={selectedEntry?.id ?? ""}
                onChange={(event) => selectEntry(event.target.value)}
              >
                {patientFacingEntries.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.title} · version {entry.current_version}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Communication purpose
              <select
                aria-label="Communication purpose"
                value={purpose}
                onChange={(event) => selectPurpose(
                  event.target.value as DeliveryItem["communication_purpose"],
                )}
              >
                <option value="care_summary">Care summary</option>
                <option value="patient_instruction">Patient instruction</option>
                <option value="appointment_invitation">Appointment invitation · acknowledgement required</option>
              </select>
            </label>
          </div>
          <div
            className={`terminology-gate terminology-${terminology?.status ?? "missing"}`}
            role="group"
            aria-label="Medication terminology release gate"
          >
            <div className="terminology-title">
              {terminologyReady ? <ShieldCheck size={16} /> : <CircleAlert size={16} />}
              <strong>{terminologyLabel(terminology)}</strong>
              {terminology && <code>{terminology.policy_version}</code>}
            </div>
            {terminology?.dose_mentions.length ? (
              <ul className="terminology-evidence">
                {terminology.dose_mentions.map((mention) => (
                  <li key={`${mention.source_start}-${mention.source_end}`}>
                    <span>{mention.medication_name ?? "Unlinked dose"}</span>
                    <strong>{mention.normalized_value} {mention.normalized_unit}</strong>
                    <small>Exact source: “{mention.source_text}” · chars {mention.source_start}–{mention.source_end}</small>
                  </li>
                ))}
              </ul>
            ) : terminology && (
              <p className="terminology-empty">
                {terminology.status === "not_applicable"
                  ? "The deterministic scanner found no medication or dose expression in this copy."
                  : "Medication wording is present, but there is no structured medication-dose pair to reference."}
              </p>
            )}
            {terminology?.unresolved.map((issue) => (
              <p className="terminology-issue" key={`${issue.code}-${issue.source_start}`}>
                <CircleAlert size={13} /><strong>{issue.source_text}</strong> — {issue.message}
              </p>
            ))}
            {terminology?.semantic_review_required && (
              <p className="terminology-warning">
                Multiple or contrastive dose statements are present. Confirm which statement is intended;
                the scanner does not infer clinical intent.
              </p>
            )}
            {terminology && (
              <details>
                <summary>What this check does — and does not prove</summary>
                <p>{terminology.decision_boundary}</p>
                <p>
                  This demo used its project-authored local vocabulary; no external terminology lookup was
                  performed. Production target: {terminology.adapter.production_target}.
                </p>
              </details>
            )}
          </div>
          <div className="attestation-grid">
            <label><input type="checkbox" checked={attestations.clinical} onChange={() => toggle("clinical")} />I reviewed the exact patient-facing copy.</label>
            <label><input type="checkbox" checked={attestations.identity} onChange={() => toggle("identity")} />I verified the patient and contact route.</label>
            <label className={doseSensitive ? "dose-required" : ""}><input type="checkbox" checked={attestations.medication} onChange={() => toggle("medication")} />I verified every medication and dose {doseSensitive ? "(required)" : "(if present)"}.</label>
            {appointmentSelected && <label className="appointment-required"><input type="checkbox" checked={attestations.appointment} onChange={() => toggle("appointment")} />I verified the appointment date, time, location, and exact link (required).</label>}
          </div>
          <button
            className="delivery-primary"
            disabled={busy || !readyToQueue}
            onClick={() => selectedEntry && preferredContact
              && void onQueue(selectedEntry, preferredContact.id, purpose, attestations)}
          >
            <ShieldCheck size={15} /> Queue approved copy
          </button>
        </div>
      )}

      <div className="delivery-ledger" aria-label="Immutable delivery ledger">
        {readiness.deliveries.length === 0 && (
          <div className="delivery-empty"><Send size={18} />No patient communication has been queued.</div>
        )}
        {readiness.deliveries.slice(0, 4).map((delivery) => {
          const currentEntry = entriesById.get(delivery.source_entry_id);
          const correctionEligible = role === "clinician"
            && delivery.status === "delivered"
            && !delivery.source_is_current
            && currentEntry
            && preferredContact;
          const correctingSelectedEntry = currentEntry?.id === selectedEntry?.id;
          const correctingPurposeMatches = delivery.communication_purpose === purpose;
          return (
            <article key={delivery.id} className={`delivery-row delivery-${delivery.status}`}>
              <div className="delivery-status-icon"><StatusIcon status={delivery.status} /></div>
              <div className="delivery-copy">
                <div>
                  <strong>{delivery.status.replaceAll("_", " ")}</strong>
                  <span>{delivery.channel} · {delivery.masked_destination}</span>
                  <em>{delivery.communication_purpose.replaceAll("_", " ")}</em>
                  {delivery.correction_for_id && <em>Correction</em>}
                </div>
                <p>{delivery.receipt_meaning}</p>
                <details>
                  <summary>View immutable sent copy</summary>
                  <blockquote>{delivery.content_snapshot}</blockquote>
                  <code>{delivery.content_hash.slice(0, 16)}…</code>
                </details>
                {delivery.follow_up && (
                  <div className={`delivery-follow-up follow-up-${delivery.follow_up.status}`}>
                    <strong>{delivery.follow_up.status.replaceAll("_", " ")}</strong>
                    <span>
                      {delivery.follow_up.acknowledge_by
                        ? `Patient acknowledgement due ${new Date(delivery.follow_up.acknowledge_by).toLocaleString("en-SG")}`
                        : "Acknowledgement clock starts only after provider-confirmed delivery."}
                    </span>
                    {delivery.follow_up.acknowledged_at && (
                      <small>Patient confirmed {new Date(delivery.follow_up.acknowledged_at).toLocaleString("en-SG")}</small>
                    )}
                  </div>
                )}
                {!delivery.source_is_current && delivery.status !== "superseded" && (
                  <div className="delivery-warning"><CircleAlert size={13} />The source note has changed. This sent copy has not changed.</div>
                )}
                {correctionEligible && (
                  <button
                    className="delivery-correction"
                    disabled={busy || !readyToQueue || !correctingSelectedEntry || !correctingPurposeMatches}
                    onClick={() => void onCorrect(
                      delivery,
                      currentEntry,
                      preferredContact.id,
                      attestations,
                    )}
                  >
                    <RefreshCw size={13} /> Queue current version as correction
                  </button>
                )}
                {role === "admin" && delivery.status === "queued" && (
                  <button
                    className="receipt-simulator"
                    disabled={busy}
                    onClick={() => void onTransition(delivery, "accepted")}
                  >Record synthetic provider acceptance</button>
                )}
                {role === "admin" && delivery.status === "accepted" && (
                  <button
                    className="receipt-simulator"
                    disabled={busy}
                    onClick={() => void onTransition(delivery, "delivered")}
                  >Record synthetic delivery receipt</button>
                )}
                {role === "patient"
                  && delivery.status === "delivered"
                  && ["awaiting_patient_acknowledgement", "escalated"].includes(
                    delivery.follow_up?.status ?? "",
                  ) && (
                  <button
                    className="delivery-acknowledge"
                    disabled={busy}
                    onClick={() => void onAcknowledge(delivery)}
                  >I received this appointment invitation</button>
                )}
              </div>
            </article>
          );
        })}
      </div>
      {role !== "patient" && (
        <button className="follow-up-sweep" disabled={busy} onClick={() => void onSweep()}>
          <RefreshCw size={13} /> Check failed or overdue appointment invitations
        </button>
      )}
      <p className="delivery-contract">{readiness.safety_contract}</p>
    </section>
  );
}
