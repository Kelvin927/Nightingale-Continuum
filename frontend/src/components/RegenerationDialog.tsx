import { type FormEvent, useState } from "react";
import { AlertTriangle, Bot, CheckCircle2, LockKeyhole } from "lucide-react";

import type { Entry, RegenerationResult } from "../types";
import { DialogShell } from "./Dialogs";

const SYNTHETIC_REHEARSAL =
  "During this synthetic rehearsal, the patient reports that lisinopril remains at 20 mg and the follow-up is pending.";

export function RegenerationDialog({
  entry,
  onClose,
  onRegenerate,
}: {
  entry: Entry;
  onClose: () => void;
  onRegenerate: (transcript: string) => Promise<RegenerationResult>;
}) {
  const [transcript, setTranscript] = useState(SYNTHETIC_REHEARSAL);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RegenerationResult | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await onRegenerate(transcript));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Regeneration failed safely.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <DialogShell title="Regenerate AI proposal" eyebrow={`Proposal version ${entry.current_version}`} onClose={onClose} wide>
      <div className="regeneration-contract">
        <LockKeyhole size={18} />
        <div>
          <strong>Only a new AI proposal may be created.</strong>
          <p>Human-confirmed entries, decisions, completed tasks, released copies, and reviewed safety signals are protected state.</p>
        </div>
      </div>
      {result ? (
        <div className="preservation-receipt">
          <div className="preservation-heading">
            <CheckCircle2 size={20} />
            <div><strong>Protected state unchanged</strong><span>New proposal {result.entry_id.slice(0, 8)}…</span></div>
          </div>
          <div className="preservation-counts">
            <span><strong>{result.preservation_receipt.protected_highlight_count}</strong>decided highlights</span>
            <span><strong>{result.preservation_receipt.completed_task_count}</strong>completed tasks</span>
            <span><strong>{result.preservation_receipt.resolved_conflict_count}</strong>resolved conflicts</span>
            <span><strong>{result.preservation_receipt.released_delivery_count}</strong>released copies</span>
            <span><strong>{result.preservation_receipt.reviewed_signal_count}</strong>reviewed signals</span>
          </div>
          <p>{result.preservation_receipt.meaning}</p>
          <code>state sha256 {result.preservation_receipt.protected_state_hash}</code>
          <button className="primary-button" onClick={onClose}>Return to timeline</button>
        </div>
      ) : (
        <form className="dialog-form" onSubmit={submit}>
          <label>
            Corrected source transcript for a new proposal
            <textarea
              rows={7}
              value={transcript}
              onChange={(event) => setTranscript(event.target.value)}
              required
              autoFocus
            />
          </label>
          <div className="policy-callout">
            <Bot size={16} />
            <span>The prior AI entry remains immutable. This rehearsal uses synthetic text and creates a separate unconfirmed proposal.</span>
          </div>
          {error && <div className="form-error"><AlertTriangle size={15} />{error}</div>}
          <div className="modal-actions">
            <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
            <button className="primary-button" disabled={busy || transcript.trim().length < 6}>
              {busy ? "Checking protected state..." : "Create separate proposal"}
            </button>
          </div>
        </form>
      )}
    </DialogShell>
  );
}
