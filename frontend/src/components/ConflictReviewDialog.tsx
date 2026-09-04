import { useState } from "react";
import { AlertTriangle, ArrowUpRight, CheckCircle2, GitCompareArrows, ShieldCheck } from "lucide-react";

import type { ConflictItem, ConflictSource, Role } from "../types";
import { DialogShell } from "./Dialogs";

type Decision = "confirm_left" | "confirm_right" | "escalate_unresolved";

function SourceCard({ label, source }: { label: string; source: ConflictSource }) {
  if (source.state === "unavailable") {
    return (
      <article className="conflict-source unavailable">
        <span className="eyebrow">{label}</span>
        <h3>Source unavailable</h3>
        <p>The decision must remain unresolved until this immutable version is restored.</p>
        <code>{source.version_id}</code>
      </article>
    );
  }
  return (
    <article className="conflict-source">
      <div className="conflict-source-heading">
        <div><span className="eyebrow">{label}</span><h3>{source.entry_title}</h3></div>
        <span className={source.source_is_current ? "source-current" : "source-stale"}>{source.source_is_current ? "Current source" : "Stale source"}</span>
      </div>
      <div className="conflict-source-meta">
        <span>{source.author?.display_name ?? "Unknown author"} · {source.owner_role}</span>
        <span>Version {source.version} · {source.trust_state?.replaceAll("_", " ")}</span>
      </div>
      <blockquote>{source.content}</blockquote>
      <code>sha256 {source.content_hash?.slice(0, 18)}…</code>
    </article>
  );
}

export function ConflictReviewDialog({
  conflict,
  role,
  busy,
  onClose,
  onResolve,
}: {
  conflict: ConflictItem;
  role: Role;
  busy: boolean;
  onClose: () => void;
  onResolve: (decision: Decision, rationale: string, sourcesReviewed: boolean) => Promise<void>;
}) {
  const [sourcesReviewed, setSourcesReviewed] = useState(false);
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function resolve(decision: Decision) {
    setError(null);
    try {
      await onResolve(decision, rationale, sourcesReviewed);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Conflict review failed.");
    }
  }

  const ready = sourcesReviewed && rationale.trim().length >= 8;
  return (
    <DialogShell
      title="Contradiction review"
      eyebrow={conflict.conflict_type.replaceAll("_", " ")}
      onClose={onClose}
      wide
    >
      <div className="conflict-review-intro">
        <GitCompareArrows size={20} />
        <div><strong>{conflict.summary}</strong><p>{conflict.decision_policy}</p></div>
      </div>
      <div className="conflict-source-grid">
        <SourceCard label="Assertion A" source={conflict.left} />
        <SourceCard label="Assertion B" source={conflict.right} />
      </div>
      {conflict.status === "open" && role === "clinician" ? (
        <div className="conflict-decision">
          <label className="checkbox-row">
            <input type="checkbox" checked={sourcesReviewed} onChange={(event) => setSourcesReviewed(event.target.checked)} />
            <span><strong>I reviewed both immutable source versions</strong><small>This attestation is required; the system never selects a winner.</small></span>
          </label>
          <label>Clinical rationale<textarea rows={3} value={rationale} onChange={(event) => setRationale(event.target.value)} placeholder="Document why one assertion is confirmed, or why this remains unresolved." /></label>
          {error && <div className="form-error"><AlertTriangle size={15} />{error}</div>}
          <div className="conflict-actions">
            <button disabled={busy || !ready} onClick={() => resolve("confirm_left")}><CheckCircle2 size={14} />Confirm assertion A</button>
            <button className="escalate-button" disabled={busy || !ready} onClick={() => resolve("escalate_unresolved")}><ArrowUpRight size={14} />Escalate unresolved</button>
            <button className="primary-button" disabled={busy || !ready} onClick={() => resolve("confirm_right")}><CheckCircle2 size={14} />Confirm assertion B</button>
          </div>
        </div>
      ) : (
        <div className="conflict-resolution-result">
          <ShieldCheck size={17} />
          <div><strong>{conflict.status === "open" ? "Clinician review required" : conflict.status}</strong><p>{conflict.resolution.rationale ?? "This role can inspect the contradiction but cannot resolve it."}</p></div>
        </div>
      )}
    </DialogShell>
  );
}
