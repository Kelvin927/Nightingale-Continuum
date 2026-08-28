import { Activity, AlertTriangle, BarChart3, BookOpenCheck, FlaskConical, Sigma } from "lucide-react";

import type { PolicyEvaluation } from "../types";

export function ResearchPanel({ evaluation }: { evaluation: PolicyEvaluation | null }) {
  const estimate = evaluation?.doubly_robust_value;
  return (
    <section className="research-panel" aria-labelledby="research-title">
      <div className="research-hero">
        <div><span className="eyebrow">Policy lab - synthetic interactions</span><h2 id="research-title">Learn safely before changing attention</h2><p>Clinician feedback informs a bounded ranking adjustment. Candidate policies remain in shadow mode until overlap, sample size, uncertainty, and safety gates are credible.</p></div>
        <div className="shadow-stamp"><FlaskConical /><strong>Shadow only</strong><span>No autonomous clinical action</span></div>
      </div>
      <div className="metric-grid">
        <article><span>Observed interactions</span><strong>{evaluation?.observations ?? 0}</strong><small>Append-only feedback records</small></article>
        <article><span>Effective sample size</span><strong>{evaluation?.effective_sample_size?.toFixed(1) ?? "-"}</strong><small>Importance-weighted support</small></article>
        <article><span>DR policy value</span><strong>{estimate == null ? "Not estimated" : `${(estimate * 100).toFixed(1)}%`}</strong><small>Acceptance relevance proxy</small></article>
        <article><span>Evaluation status</span><strong className="status-text">{evaluation?.status.replaceAll("_", " ") ?? "Loading"}</strong><small>Never a clinical efficacy claim</small></article>
      </div>
      <div className="research-grid">
        <article className="method-card"><div className="method-icon"><Sigma /></div><h3>Named estimand</h3><p>{evaluation?.estimand ?? "Loading estimand..."}</p></article>
        <article className="method-card"><div className="method-icon"><BarChart3 /></div><h3>Doubly robust estimate</h3><p>Combines a reward model with inverse propensity weighting. Either nuisance component must be credible, and both still need adequate overlap.</p></article>
        <article className="method-card"><div className="method-icon"><Activity /></div><h3>Bounded learning</h3><p>Beta posterior shrinkage limits sparse feedback to +/-0.75 points. Critical risks and medication/allergy signals stay in protected bands.</p></article>
      </div>
      <div className="assumption-panel"><div className="assumption-title"><BookOpenCheck size={18} /><div><h3>Identification assumptions</h3><p>Visible because off-policy estimates are conditional, not magic.</p></div></div><ol>{evaluation?.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ol></div>
      {(evaluation?.overlap_warning || evaluation?.exposure_bias_warning || evaluation?.status === "insufficient_data") && <div className="research-warning"><AlertTriangle size={18} /><div><strong>Do not promote this policy.</strong><p>The synthetic evidence is insufficient for a reliable policy comparison. Only surfaced items receive feedback in this deterministic prototype, so exposure bias and overlap must be addressed before promotion.</p></div></div>}
    </section>
  );
}
