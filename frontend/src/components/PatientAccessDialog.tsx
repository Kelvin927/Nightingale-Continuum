import { type FormEvent, useMemo, useState } from "react";
import {
  CheckCircle2,
  Clock3,
  KeyRound,
  MailX,
  MessageCircle,
  ShieldCheck,
  Smartphone,
  UserCheck,
} from "lucide-react";

import type {
  DeliveryContact,
  Patient,
  PatientAccessClaim,
  PatientAccessProof,
} from "../types";
import { DialogShell } from "./Dialogs";

type AccessPurpose = PatientAccessClaim["purpose"];

export function PatientAccessDialog({
  patient,
  contact,
  onClose,
  onIssue,
  onRedeem,
}: {
  patient: Patient;
  contact: DeliveryContact;
  onClose: () => void;
  onIssue: (payload: {
    contactId: string;
    purpose: AccessPurpose;
    ttlMinutes: number;
  }) => Promise<PatientAccessClaim>;
  onRedeem: (payload: {
    claimToken: string;
    recordNumber: string;
    dateOfBirth: string;
  }) => Promise<PatientAccessProof>;
}) {
  const [purpose, setPurpose] = useState<AccessPurpose>("portal_access");
  const [ttlMinutes, setTtlMinutes] = useState(10);
  const [claim, setClaim] = useState<PatientAccessClaim | null>(null);
  const [proof, setProof] = useState<PatientAccessProof | null>(null);
  const [recordNumber, setRecordNumber] = useState(patient.synthetic_record_number);
  const [dateOfBirth, setDateOfBirth] = useState(patient.date_of_birth);
  const [busy, setBusy] = useState<"issue" | "redeem" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const visibleEntries = useMemo(
    () => proof?.workspace.entries.filter((entry) => entry.visibility === "patient") ?? [],
    [proof],
  );

  async function issueClaim() {
    setBusy("issue");
    setError(null);
    setClaim(null);
    setProof(null);
    try {
      setClaim(await onIssue({ contactId: contact.id, purpose, ttlMinutes }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The access claim was not issued.");
    } finally {
      setBusy(null);
    }
  }

  async function redeemClaim(event: FormEvent, activeClaim: PatientAccessClaim) {
    event.preventDefault();
    setBusy("redeem");
    setError(null);
    try {
      setProof(await onRedeem({
        claimToken: activeClaim.demo_claim_token,
        recordNumber,
        dateOfBirth,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The access claim could not be verified.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <DialogShell
      title="Phone-only patient access"
      eyebrow="Channel-neutral identity bridge"
      onClose={onClose}
      wide
    >
      <div className="access-contract-grid">
        <div><MailX /><strong>No email dependency</strong><span>A verified, consented care channel carries a one-time claim.</span></div>
        <div><KeyRound /><strong>Short-lived and single-use</strong><span>Only a SHA-256 token digest is retained; five failures lock the claim.</span></div>
        <div><UserCheck /><strong>Patient-only projection</strong><span>The resulting session is bound to one patient and cannot reveal internal notes.</span></div>
      </div>

      {!claim && (
        <section className="access-step">
          <div className="access-step-heading">
            <span>1</span>
            <div><strong>Issue through the verified channel</strong><small>This rehearsal creates a claim but does not contact a real provider.</small></div>
          </div>
          <div className="access-issue-grid">
            <div className="access-route-card">
              {contact.channel === "whatsapp" ? <MessageCircle /> : <Smartphone />}
              <span><strong>{contact.channel}</strong><small>{contact.masked_destination}</small></span>
              <ShieldCheck />
            </div>
            <label>
              Access purpose
              <select value={purpose} onChange={(event) => setPurpose(event.target.value as AccessPurpose)}>
                <option value="portal_access">Portal access</option>
                <option value="intake">Pre-visit intake</option>
                <option value="summary">Care summary</option>
                <option value="instructions">Care instructions</option>
              </select>
            </label>
            <label>
              Claim lifetime
              <select value={ttlMinutes} onChange={(event) => setTtlMinutes(Number(event.target.value))}>
                <option value={5}>5 minutes</option>
                <option value={10}>10 minutes</option>
                <option value={15}>15 minutes</option>
              </select>
            </label>
          </div>
          <button className="primary-button" disabled={busy !== null} onClick={issueClaim}>
            <KeyRound size={15} />{busy === "issue" ? "Issuing safely..." : "Create one-time access claim"}
          </button>
        </section>
      )}

      {claim && !proof && (
        <form className="access-step" onSubmit={(event) => redeemClaim(event, claim)}>
          <div className="access-step-heading complete">
            <CheckCircle2 />
            <div><strong>Claim created for {claim.masked_destination}</strong><small>No message was sent in this synthetic rehearsal.</small></div>
          </div>
          <div className="access-demo-token">
            <span>Synthetic one-time claim shown once</span>
            <code>{claim.demo_claim_token}</code>
            <small>{claim.security_note}</small>
          </div>
          <div className="access-step-heading">
            <span>2</span>
            <div><strong>Verify two patient-held factors</strong><small>The API returns the same generic error for an invalid token or identity factors.</small></div>
          </div>
          <div className="access-verification-grid">
            <label>
              Synthetic record number
              <input value={recordNumber} onChange={(event) => setRecordNumber(event.target.value)} required />
            </label>
            <label>
              Date of birth
              <input type="date" value={dateOfBirth} onChange={(event) => setDateOfBirth(event.target.value)} required />
            </label>
          </div>
          <div className="access-expiry"><Clock3 />Claim expires {new Date(claim.expires_at).toLocaleString("en-SG")}</div>
          <div className="modal-actions">
            <button type="button" className="secondary-button" onClick={() => setClaim(null)}>Issue another</button>
            <button className="primary-button" disabled={busy !== null || !recordNumber || !dateOfBirth}>
              {busy === "redeem" ? "Verifying scope..." : "Verify and open patient view"}
            </button>
          </div>
        </form>
      )}

      {proof && (
        <section className="access-proof">
          <div className="access-proof-heading">
            <CheckCircle2 />
            <div><strong>Authenticated without email</strong><span>Channel claim accepted; patient scope independently re-read.</span></div>
          </div>
          <dl>
            <div><dt>Authentication</dt><dd>{proof.viewer.authentication_mode.replaceAll("_", " ")}</dd></div>
            <div><dt>Authorized role</dt><dd>{proof.viewer.role}</dd></div>
            <div><dt>Patient scope</dt><dd>{proof.workspace.patient.synthetic_record_number}</dd></div>
            <div><dt>Email required</dt><dd>no</dd></div>
          </dl>
          <div className="access-projection">
            <span>Patient-visible longitudinal projection</span>
            <strong>{visibleEntries.length} visible {visibleEntries.length === 1 ? "entry" : "entries"}</strong>
            {visibleEntries.length > 0 ? (
              <ul>{visibleEntries.map((entry) => <li key={entry.id}><ShieldCheck />{entry.title}</li>)}</ul>
            ) : <p>No clinician-approved patient-facing entry is available yet.</p>}
          </div>
          <p className="access-boundary">This proves the prototype authorization path with synthetic data. Production deployment still requires an approved messaging provider, identity policy, credential lifecycle, penetration testing, and a narrowly scoped PostgreSQL authentication broker.</p>
          <button className="primary-button" onClick={onClose}>Return to clinician view</button>
        </section>
      )}

      {error && <div className="form-error" role="alert"><ShieldCheck size={15} />{error}</div>}
    </DialogShell>
  );
}
