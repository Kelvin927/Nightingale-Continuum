import { useEffect, useState } from "react";
import { AlertTriangle, GitMerge, History, ShieldCheck } from "lucide-react";

import type { VersionConflictDetail } from "../types";
import { DialogShell } from "./Dialogs";

function VersionPanel({
  label,
  version,
  content,
  contentHash,
}: {
  label: string;
  version: number | string;
  content: string;
  contentHash: string | null;
}) {
  return (
    <article className="merge-version-panel">
      <div>
        <span className="eyebrow">{label}</span>
        <strong>Version {version}</strong>
      </div>
      <pre>{content}</pre>
      <code>{contentHash ? `sha256 ${contentHash.slice(0, 18)}…` : "Unsaved draft"}</code>
    </article>
  );
}

export function ConcurrentEditDialog({
  detail,
  onClose,
  onUseDraft,
}: {
  detail: VersionConflictDetail;
  onClose: () => void;
  onUseDraft: (content: string) => void;
}) {
  const suggested = detail.merge_assistance?.merged_content ?? detail.proposed_content ?? "";
  const [draft, setDraft] = useState(suggested);
  const [reviewed, setReviewed] = useState(false);

  useEffect(() => {
    setDraft(suggested);
    setReviewed(false);
  }, [detail, suggested]);

  const base = detail.base_snapshot;
  const current = detail.current_snapshot;
  const mergeSafe = detail.merge_assistance?.auto_merge_safe === true;

  return (
    <DialogShell title="Concurrent edit review" eyebrow="No silent overwrite" onClose={onClose} wide>
      <div className="merge-alert">
        <AlertTriangle size={18} />
        <div>
          <strong>The record changed while you were editing.</strong>
          <p>{detail.resolution}</p>
        </div>
      </div>

      <div className="merge-version-grid">
        <VersionPanel
          label="Base you opened"
          version={base?.version ?? detail.expected_version}
          content={base?.content ?? "Base version unavailable. Compare manually and fail closed."}
          contentHash={base?.content_hash ?? null}
        />
        <VersionPanel
          label="Current record"
          version={current?.version ?? detail.current_version}
          content={current?.content ?? "Current version unavailable. Do not resubmit."}
          contentHash={current?.content_hash ?? null}
        />
        <VersionPanel
          label="Your unsaved edit"
          version="draft"
          content={detail.proposed_content ?? "Proposed content unavailable."}
          contentHash={detail.proposed_content_hash}
        />
      </div>

      <div className={`merge-status ${mergeSafe ? "safe" : "manual"}`}>
        {mergeSafe ? <GitMerge size={17} /> : <History size={17} />}
        <div>
          <strong>
            {mergeSafe ? "Non-overlapping merge draft available" : "Manual reconciliation required"}
          </strong>
          <p>
            {mergeSafe
              ? "The line edits do not overlap. The result is still only a draft and has not been saved."
              : "Changes overlap or evidence is incomplete. No automatic merge has been produced."}
          </p>
        </div>
      </div>

      <label className="merge-draft-field">
        Reviewed draft
        <textarea
          rows={8}
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            setReviewed(false);
          }}
          aria-describedby="merge-draft-help"
        />
        <small id="merge-draft-help">
          Edit this draft while comparing all three panels. Opening it does not save anything.
        </small>
      </label>
      <label className="checkbox-row merge-attestation">
        <input
          type="checkbox"
          checked={reviewed}
          onChange={(event) => setReviewed(event.target.checked)}
        />
        <span>
          <strong>I compared the base, current record, and my draft</strong>
          <small>A fresh save will create another immutable version against the current version.</small>
        </span>
      </label>
      <div className="modal-actions">
        <button className="secondary-button" onClick={onClose}>Keep current record</button>
        <button
          className="primary-button"
          disabled={!current || !reviewed || !draft.trim()}
          onClick={() => onUseDraft(draft)}
        >
          <ShieldCheck size={14} />Open reviewed draft
        </button>
      </div>
    </DialogShell>
  );
}
