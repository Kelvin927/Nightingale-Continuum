import { FormEvent, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  FileClock,
  LockKeyhole,
  MessageSquareText,
  Mic,
  Radio,
  RotateCcw,
  Send,
  ShieldCheck,
  Square,
  X,
} from "lucide-react";

import type { Entry, EntryVersion, Role } from "../types";

function DialogShell({
  title,
  eyebrow,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  eyebrow: string;
  children: React.ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <button className="modal-scrim" onClick={onClose} aria-label="Close dialog" />
      <div className={`modal-card ${wide ? "modal-wide" : ""}`}>
        <div className="modal-header">
          <div><span className="eyebrow">{eyebrow}</span><h2 id="modal-title">{title}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close dialog"><X /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

const defaults: Record<Role, { type: string; title: string; visibility: string }> = {
  clinician: { type: "clinician_note", title: "Clinical update", visibility: "internal" },
  staff: { type: "staff_note", title: "Workflow update", visibility: "internal" },
  patient: { type: "patient_insight", title: "What I want my care team to know", visibility: "patient" },
  admin: { type: "", title: "", visibility: "internal" },
};

export function NoteDialog({
  role,
  editing,
  onClose,
  onSubmit,
}: {
  role: Role;
  editing: Entry | null;
  onClose: () => void;
  onSubmit: (payload: { title: string; content: string; entryType: string; visibility: string }) => Promise<void>;
}) {
  const initial = defaults[role];
  const [title, setTitle] = useState(editing?.title ?? initial.title);
  const [content, setContent] = useState(editing?.version.content ?? "");
  const [patientFacing, setPatientFacing] = useState(editing?.visibility === "patient");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        title,
        content,
        entryType: editing?.entry_type ?? (patientFacing && role === "clinician" ? "patient_summary" : initial.type),
        visibility: patientFacing ? "patient" : initial.visibility,
      });
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save the note.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <DialogShell
      title={editing ? `Edit ${editing.title}` : initial.title}
      eyebrow={editing ? `Role-owned section - version ${editing.current_version}` : "New longitudinal entry"}
      onClose={onClose}
      wide
    >
      <form className="dialog-form" onSubmit={submit}>
        <label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
        <label>Note content<textarea value={content} onChange={(event) => setContent(event.target.value)} rows={9} required autoFocus /></label>
        {role === "clinician" && !editing && (
          <label className="checkbox-row">
            <input type="checkbox" checked={patientFacing} onChange={(event) => setPatientFacing(event.target.checked)} />
            <span><strong>Patient-facing summary</strong><small>Only clinician-confirmed content should be shared.</small></span>
          </label>
        )}
        <div className="policy-callout"><LockKeyhole size={16} /><span>You can edit only sections owned by your current role. Saving creates a new immutable version.</span></div>
        {error && <div className="form-error"><AlertTriangle size={15} />{error}</div>}
        <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={busy || !content.trim()}>{busy ? "Saving..." : "Save version"}</button></div>
      </form>
    </DialogShell>
  );
}

export function CommentDialog({
  entry,
  collaborator,
  onClose,
  onSubmit,
}: {
  entry: Entry;
  collaborator: { id: string; name: string } | null;
  onClose: () => void;
  onSubmit: (title: string, body: string, assignedTo: string | null) => Promise<void>;
}) {
  const [title, setTitle] = useState("Review this entry");
  const [body, setBody] = useState("");
  const [assigned, setAssigned] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSubmit(title, body, assigned ? collaborator!.id : null);
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <DialogShell title="Start a review thread" eyebrow={entry.title} onClose={onClose}>
      <form className="dialog-form" onSubmit={submit}>
        <label>Thread title<input value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
        <label>Comment<textarea value={body} onChange={(event) => setBody(event.target.value)} rows={5} required autoFocus /></label>
        {collaborator && <label className="checkbox-row"><input type="checkbox" checked={assigned} onChange={(event) => setAssigned(event.target.checked)} /><span><strong>Assign to {collaborator.name}</strong><small>Adds explicit ownership to this handoff.</small></span></label>}
        <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={busy || !body.trim()}><MessageSquareText size={15} />{busy ? "Posting..." : "Post thread"}</button></div>
      </form>
    </DialogShell>
  );
}

export function HistoryDialog({
  entry,
  versions,
  loading,
  onClose,
  onRevert,
}: {
  entry: Entry;
  versions: EntryVersion[];
  loading: boolean;
  onClose: () => void;
  onRevert: (targetVersion: number) => Promise<void>;
}) {
  const [busyVersion, setBusyVersion] = useState<number | null>(null);
  async function revert(version: number) {
    setBusyVersion(version);
    try { await onRevert(version); onClose(); } finally { setBusyVersion(null); }
  }
  return (
    <DialogShell title="Revision history" eyebrow={`${entry.title} - current v${entry.current_version}`} onClose={onClose} wide>
      <div className="history-explainer"><FileClock size={17} /><span>History is append-only. Revert creates a new version and preserves this entire trail.</span></div>
      {loading ? <div className="dialog-loading">Loading versions...</div> : (
        <div className="version-list">
          {versions.map((version) => (
            <article className={`version-item ${version.version === entry.current_version ? "current" : ""}`} key={version.id}>
              <div className="version-heading"><div><strong>Version {version.version}</strong><span>{new Date(version.created_at).toLocaleString("en-SG")}</span></div>{version.version === entry.current_version ? <span className="current-label"><CheckCircle2 size={13} /> Current</span> : <button disabled={busyVersion !== null} onClick={() => revert(version.version)}><RotateCcw size={13} />{busyVersion === version.version ? "Restoring..." : "Restore"}</button>}</div>
              <p>{version.change_reason}</p>
              <pre>{version.content}</pre>
              <code>{version.content_hash.slice(0, 20)}...</code>
            </article>
          ))}
        </div>
      )}
    </DialogShell>
  );
}

type CaptureStatus = "idle" | "recording" | "captured";

export function ScribeDialog({
  role,
  onClose,
  onSubmit,
}: {
  role: Role;
  onClose: () => void;
  onSubmit: (interactionType: string, transcript: string) => Promise<{ receipt: Record<string, number>; flags: string[] }>;
}) {
  const [status, setStatus] = useState<CaptureStatus>("idle");
  const [transcript, setTranscript] = useState("Maya Chen reports dizziness after lisinopril changed from 10 mg to 20 mg. Call +65 9123 4567 after the renal lab result.");
  const [result, setResult] = useState<{ receipt: Record<string, number>; flags: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const interactionType = role === "patient" ? "patient_session" : role === "staff" ? "nurse_consult" : "doctor_consult";

  useEffect(() => () => stream.current?.getTracks().forEach((track) => track.stop()), []);

  async function toggleRecording() {
    if (status === "recording") {
      recorder.current?.stop();
      stream.current?.getTracks().forEach((track) => track.stop());
      setStatus("captured");
      return;
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      recorder.current = new MediaRecorder(stream.current);
      recorder.current.start();
      setStatus("recording");
    } catch {
      setStatus("captured");
    }
  }

  async function submit() {
    setBusy(true);
    try { setResult(await onSubmit(interactionType, transcript)); } finally { setBusy(false); }
  }

  return (
    <DialogShell title="Ambient capture" eyebrow="Privacy-first PWA capture" onClose={onClose} wide>
      {!result ? (
        <div className="scribe-layout">
          <div className={`capture-orb ${status}`}><Radio size={30} /><span>{status === "recording" ? "Recording locally" : "Ready"}</span></div>
          <div className="scribe-controls">
            <button className={status === "recording" ? "danger-button" : "primary-button"} onClick={toggleRecording}>{status === "recording" ? <Square size={15} /> : <Mic size={15} />}{status === "recording" ? "Stop capture" : "Start local capture"}</button>
            <p>Audio remains on this device in the prototype. The editable synthetic transcript below demonstrates the enforced redaction and scribe boundary.</p>
          </div>
          <label className="transcript-field">Synthetic transcript<textarea value={transcript} onChange={(event) => setTranscript(event.target.value)} rows={6} /></label>
          <div className="privacy-pipeline"><span><ShieldCheck size={16} />Raw capture</span><i /><span><LockKeyhole size={16} />Redact PHI</span><i /><span><Bot size={16} />Draft</span><i /><span><CheckCircle2 size={16} />Human review</span></div>
          <div className="modal-actions"><button className="secondary-button" onClick={onClose}>Cancel</button><button className="primary-button" disabled={busy || !transcript.trim()} onClick={submit}><Send size={15} />{busy ? "Redacting..." : "Create review draft"}</button></div>
        </div>
      ) : (
        <div className="receipt-success"><CheckCircle2 size={34} /><h3>Draft submitted for human review</h3><p>The local provider received redacted text only.</p><div className="receipt-counts">{Object.entries(result.receipt).map(([name, count]) => <span key={name}><strong>{count}</strong>{name.replaceAll("_", " ")}</span>)}</div><div className="flag-list">{result.flags.map((flag) => <span key={flag}>{flag.replaceAll("_", " ")}</span>)}</div><button className="primary-button" onClick={onClose}>Return to care note</button></div>
      )}
    </DialogShell>
  );
}
