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

import type { DeliveryItem, DeliveryReadiness, Entry, Role } from "../types";

interface Attestations {
  clinical: boolean;
  identity: boolean;
  medication: boolean;
}

interface Props {
  readiness: DeliveryReadiness;
  role: Role;
  patientFacingEntries: Entry[];
  busy: boolean;
  onQueue: (entry: Entry, contactId: string, attestations: Attestations) => Promise<void>;
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
}

const MEDICATION_OR_DOSE =
  /\b(?:dose|dosage|medication|medicine|tablet|capsule|mg|mcg|g|ml|lisinopril|penicillin)\b/i;

function StatusIcon({ status }: { status: DeliveryItem["status"] }) {
  if (status === "delivered") return <CheckCircle2 size={15} />;
  if (status === "failed") return <XCircle size={15} />;
  if (status === "accepted") return <Clock3 size={15} />;
  if (status === "superseded") return <RefreshCw size={15} />;
  return <Send size={15} />;
}

export function DeliveryCenter({
  readiness,
  role,
  patientFacingEntries,
  busy,
  onQueue,
  onCorrect,
  onTransition,
}: Props) {
  const [selectedEntryId, setSelectedEntryId] = useState(patientFacingEntries[0]?.id ?? "");
  const [attestations, setAttestations] = useState<Attestations>({
    clinical: false,
    identity: false,
    medication: false,
  });
  const preferredContact = readiness.contacts.find((contact) => contact.preferred)
    ?? readiness.contacts[0];
  const selectedEntry = patientFacingEntries.find((entry) => entry.id === selectedEntryId)
    ?? patientFacingEntries[0];
  const doseSensitive = Boolean(selectedEntry && MEDICATION_OR_DOSE.test(selectedEntry.version.content));
  const readyToQueue = Boolean(
    selectedEntry
    && preferredContact
    && preferredContact.active
    && preferredContact.verified
    && preferredContact.consent_status === "granted"
    && attestations.clinical
    && attestations.identity
    && (!doseSensitive || attestations.medication),
  );
  const entriesById = useMemo(
    () => new Map(patientFacingEntries.map((entry) => [entry.id, entry])),
    [patientFacingEntries],
  );

  function toggle(key: keyof Attestations) {
    setAttestations((current) => ({ ...current, [key]: !current[key] }));
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
          <label>
            Patient-facing source
            <select
              aria-label="Patient-facing source"
              value={selectedEntry?.id ?? ""}
              onChange={(event) => setSelectedEntryId(event.target.value)}
            >
              {patientFacingEntries.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.title} · version {entry.current_version}
                </option>
              ))}
            </select>
          </label>
          <div className="attestation-grid">
            <label><input type="checkbox" checked={attestations.clinical} onChange={() => toggle("clinical")} />I reviewed the exact patient-facing copy.</label>
            <label><input type="checkbox" checked={attestations.identity} onChange={() => toggle("identity")} />I verified the patient and contact route.</label>
            <label className={doseSensitive ? "dose-required" : ""}><input type="checkbox" checked={attestations.medication} onChange={() => toggle("medication")} />I verified every medication and dose {doseSensitive ? "(required)" : "(if present)"}.</label>
          </div>
          <button
            className="delivery-primary"
            disabled={busy || !readyToQueue}
            onClick={() => selectedEntry && preferredContact
              && void onQueue(selectedEntry, preferredContact.id, attestations)}
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
          return (
            <article key={delivery.id} className={`delivery-row delivery-${delivery.status}`}>
              <div className="delivery-status-icon"><StatusIcon status={delivery.status} /></div>
              <div className="delivery-copy">
                <div>
                  <strong>{delivery.status.replaceAll("_", " ")}</strong>
                  <span>{delivery.channel} · {delivery.masked_destination}</span>
                  {delivery.correction_for_id && <em>Correction</em>}
                </div>
                <p>{delivery.receipt_meaning}</p>
                <details>
                  <summary>View immutable sent copy</summary>
                  <blockquote>{delivery.content_snapshot}</blockquote>
                  <code>{delivery.content_hash.slice(0, 16)}…</code>
                </details>
                {!delivery.source_is_current && delivery.status !== "superseded" && (
                  <div className="delivery-warning"><CircleAlert size={13} />The source note has changed. This sent copy has not changed.</div>
                )}
                {correctionEligible && (
                  <button
                    className="delivery-correction"
                    disabled={busy || !readyToQueue}
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
              </div>
            </article>
          );
        })}
      </div>
      <p className="delivery-contract">{readiness.safety_contract}</p>
    </section>
  );
}
