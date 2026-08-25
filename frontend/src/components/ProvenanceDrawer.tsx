import { CheckCircle2, ExternalLink, Fingerprint, ShieldCheck, X } from "lucide-react";

import type { ResolvedProvenance } from "../types";

export function ProvenanceDrawer({
  source,
  onClose,
}: {
  source: ResolvedProvenance;
  onClose: () => void;
}) {
  return (
    <div className="drawer-overlay" role="dialog" aria-modal="true" aria-labelledby="source-title">
      <button className="drawer-scrim" aria-label="Close source drawer" onClick={onClose} />
      <div className="provenance-drawer">
        <div className="drawer-header">
          <div>
            <span className="eyebrow">Evidence receipt</span>
            <h2 id="source-title">Verified exact source</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close source drawer"><X /></button>
        </div>
        <div className="verified-banner">
          <CheckCircle2 size={18} />
          <div><strong>Pointer verified</strong><span>Version, hash, offsets, and quote agree.</span></div>
        </div>
        <div className="source-quote">
          <span>Quoted evidence</span>
          <blockquote>{source.quote}</blockquote>
        </div>
        <dl className="evidence-grid">
          <div><dt>Source type</dt><dd>{source.source_kind.replaceAll("_", " ")}</dd></div>
          <div><dt>Immutable version</dt><dd>v{source.source_version}</dd></div>
          <div><dt>Character span</dt><dd>{source.start_offset}-{source.end_offset}</dd></div>
          <div><dt>Integrity</dt><dd><ShieldCheck size={14} /> SHA-256 verified</dd></div>
        </dl>
        <div className="hash-block">
          <Fingerprint size={16} />
          <code>{source.content_hash}</code>
        </div>
        <div className="source-pointer">
          <span>Original pointer</span>
          <p><ExternalLink size={13} /> {source.source_uri}</p>
        </div>
        <p className="drawer-note">
          This receipt proves where the displayed statement came from. It does not independently prove that the clinical statement is correct.
        </p>
      </div>
    </div>
  );
}
